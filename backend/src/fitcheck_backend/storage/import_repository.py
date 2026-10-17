"""Each method runs inside a caller-owned transaction; owner locks serialize imports."""
from sqlalchemy import select
from pydantic import ValidationError
from ..contracts.imports import ImportItemOutcome,ImportReport,LegacyAnalysisSnapshot,normalize_profile
from ..contracts.domain import FreelancerProfile
from .models import ImportItem,ImportEntry,VacancyRecord,AnalysisRecord,AnalysisAnnotation,Preference
from .job_queue import fenced_job
from .payloads import canonical_hash,encode_analysis,encode_vacancy,encode_snapshot
from .profile_repository import get_profile,create_profile


class ImportLeaseLost(Exception):
    pass


class ImportRepository:
    def __init__(self,session):self.session=session

    def _job(self,lease):
        job=fenced_job(self.session,lease,load_input=False)
        if job is None:raise ImportLeaseLost()
        return job

    def _existing(self,lease,index):
        return self.session.get(ImportItem,(lease.job_id,index))

    def _save(self,lease,index,value):
        self.session.add(ImportItem(owner_id=lease.owner_id,job_id=lease.job_id,item_index=index,outcome=value))
        self.session.flush()
        # Recheck after all possibly blocking writes, before caller commits.
        self._job(lease)
        return value

    def apply_profile(self,lease,request):
        self._job(lease)
        previous=self._existing(lease,-2)
        if previous:return previous.outcome['outcome']
        outcome='skipped'
        if request.profile is not None:
            try:profile=FreelancerProfile.model_validate(normalize_profile(request.profile))
            except ValidationError:outcome='invalid'
            else:
                current=get_profile(self.session,lease.owner_id)
                if current is None:
                    create_profile(self.session,lease.owner_id,profile);outcome='imported'
                elif current.profile!=profile:outcome='conflict'
        self._save(lease,-2,{'outcome':outcome})
        return outcome

    def apply_preferences(self,lease,request):
        self._job(lease)
        previous=self._existing(lease,-1)
        if previous:return previous.outcome['outcome']
        outcome='skipped'
        if request.locale is not None:
            current=self.session.get(Preference,lease.owner_id)
            if current is None:
                self.session.add(Preference(owner_id=lease.owner_id,locale=request.locale));outcome='imported'
            elif current.locale!=request.locale:outcome='conflict'
        self._save(lease,-1,{'outcome':outcome})
        return outcome

    def apply_row(self,lease,index,row):
        job=self._job(lease)
        previous=self._existing(lease,index)
        if previous:return ImportItemOutcome.model_validate(previous.outcome)
        digest=canonical_hash(row.model_dump(mode='json'))
        receipt=self.session.scalar(select(ImportEntry).where(ImportEntry.owner_id==lease.owner_id,
            ImportEntry.source=='local_v1',ImportEntry.source_user_id==lease.input['sourceUserId'],ImportEntry.external_id==row.id))
        if receipt:
            outcome,reason=('skipped','identical') if receipt.content_hash==digest else ('conflict','source_changed')
        else:
            vacancy=VacancyRecord(owner_id=lease.owner_id,vacancy=encode_vacancy(row.job),source_url=row.job.url,created_at=row.created_at)
            self.session.add(vacancy);self.session.flush()
            snapshot=LegacyAnalysisSnapshot(profile=row.profile,vacancy=row.job,locale=row.locale)
            record=AnalysisRecord(owner_id=lease.owner_id,vacancy_id=vacancy.id,profile_revision=None,
                snapshot=encode_snapshot(snapshot),analysis=encode_analysis(row.analysis),created_at=row.created_at)
            self.session.add(record);self.session.flush()
            feedback=row.feedback
            self.session.add(AnalysisAnnotation(owner_id=lease.owner_id,analysis_id=record.id,
                corrected_score=feedback.corrected_score if feedback else None,note=feedback.note if feedback else None,
                feedback_created_at=feedback.created_at if feedback else None))
            self.session.add(ImportEntry(owner_id=lease.owner_id,source='local_v1',source_user_id=lease.input['sourceUserId'],
                external_id=row.id,content_hash=digest,analysis_id=record.id))
            outcome,reason='imported','created'
        value=ImportItemOutcome(index=index,externalId=row.id,outcome=outcome,reason=reason)
        self._save(lease,index,value.model_dump(mode='json'))
        return value

    def record_invalid(self,lease,index,reason='invalid_record'):
        job=self._job(lease)
        previous=self._existing(lease,index)
        if previous:return ImportItemOutcome.model_validate(previous.outcome)
        raw=lease.input['history'][index]
        external_id=raw.get('id')
        if not isinstance(external_id,str) or not 1<=len(external_id.strip())<=200:external_id=None
        value=ImportItemOutcome(index=index,externalId=external_id,outcome='invalid',reason=reason)
        self._save(lease,index,value.model_dump(mode='json'))
        return value

    def report(self,job_id,owner_id):
        from .models import Job
        job=self.session.scalar(select(Job).where(Job.id==job_id,Job.owner_id==owner_id))
        if job is None:raise ImportLeaseLost()
        rows=self.session.scalars(select(ImportItem).where(ImportItem.job_id==job_id,ImportItem.owner_id==owner_id).order_by(ImportItem.item_index)).all()
        items=[ImportItemOutcome.model_validate(r.outcome) for r in rows if r.item_index>=0]
        meta={r.item_index:r.outcome['outcome'] for r in rows if r.item_index<0}
        return ImportReport(totalCount=len(job.input['history']),importedCount=sum(i.outcome=='imported' for i in items),
            skippedCount=sum(i.outcome=='skipped' for i in items),conflictCount=sum(i.outcome=='conflict' for i in items),
            invalidCount=sum(i.outcome=='invalid' for i in items),profileOutcome=meta.get(-2),preferencesOutcome=meta.get(-1),items=items)
