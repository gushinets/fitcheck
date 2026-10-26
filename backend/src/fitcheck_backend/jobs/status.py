from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError
from ..contracts.jobs import JobState
from ..storage.models import Job, AnalysisRecord, AnalysisAnnotation, Profile
from ..storage.history_repository import analysis_resource
from ..storage.job_queue import job_transaction
from .errors import JobError
from ..storage.base import utcnow
from ..storage.guest_repository import require_identity


class JobStatusReader:
    def __init__(self, engine, *, clock=utcnow):
        self.engine,self.clock = engine,clock

    def get(self, *, owner_id, job_id, identity=None):
        try:
            with job_transaction(self.engine) as s:
                if identity is not None: require_identity(s,identity,self.clock())
                row = s.execute(select(Job,AnalysisRecord,AnalysisAnnotation,Profile.current_revision)
                    .outerjoin(AnalysisRecord,and_(AnalysisRecord.job_id == Job.id,
                        AnalysisRecord.owner_id == Job.owner_id))
                    .outerjoin(AnalysisAnnotation,and_(AnalysisAnnotation.analysis_id == AnalysisRecord.id,
                        AnalysisAnnotation.owner_id == Job.owner_id))
                    .outerjoin(Profile, Profile.owner_id == Job.owner_id)
                    .where(Job.id == job_id,Job.owner_id == owner_id,
                        Job.type.in_(['analysis','skill_suggestions']))).first()
                if row is None: raise JobError('not_found')
                job,analysis,annotation,current_revision = row
                value = dict(jobId=str(job.id),type=job.type,status=job.status)
                if job.status == 'failed': value['error'] = job.error
                if job.status == 'succeeded':
                    if job.type == 'skill_suggestions': value['skills'] = job.output['skills']
                    else:
                        if analysis is None: raise JobError('not_found')
                        result = analysis_resource(analysis, annotation, current_revision)
                        value.update(analysisId=str(analysis.id),result=result.model_dump(mode='json'))
                return JobState.model_validate(value)
        except (SQLAlchemyError, ValidationError, KeyError, ValueError):
            raise JobError('service_unavailable') from None
