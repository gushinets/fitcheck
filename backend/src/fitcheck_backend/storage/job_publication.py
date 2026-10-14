from pydantic import TypeAdapter
from sqlalchemy import update, select
from ..contracts.domain import Skill
from ..contracts.resources import AnalysisSnapshot
from ..jobs.envelope import decode_envelope, AnalysisEnvelope
from .models import VacancyRecord, AnalysisRecord, AnalysisAnnotation, ProviderCall, Owner
from .payloads import encode_analysis, encode_snapshot
from .job_queue import job_transaction, fenced_job, db_now
from ..metrics.lifecycle import append_job_finished


class _LostLease(Exception):
    pass


def _finish(session, job, *, status, output=None, error=None, metrics_environment=None):
    now = db_now(session)
    if job.lease_expires_at <= now:
        raise _LostLease()
    job.status, job.finished_at = status, now
    job.output, job.error = output, error
    job.lease_token, job.lease_expires_at = None, None
    append_job_finished(session, job, metrics_environment)


class JobPublication:
    def __init__(self, engine, *, metrics_environment=None):
        self.engine = engine
        self.metrics_environment = metrics_environment

    def _fenced_job(self, session, lease):
        if self.metrics_environment is not None:
            owner = session.scalar(select(Owner.id).where(Owner.id==lease.owner_id)
                .with_for_update(read=True, key_share=True))
            if owner is None:
                return None
        return fenced_job(session, lease)

    def succeed_analysis(self, lease, result):
        if lease.type != 'analysis':
            raise ValueError('Invalid publication type')
        try:
            with job_transaction(self.engine) as s:
                job = self._fenced_job(s, lease)
                if job is None:
                    return None
                envelope = decode_envelope(job.type, job.input)
                expected = AnalysisSnapshot(profileRevision=envelope.request.profile_revision,
                    profile=envelope.profile, vacancy=envelope.request.vacancy, locale=envelope.request.locale,
                    promptVersion=envelope.versions.prompt_version, schemaVersion=envelope.versions.schema_version,
                    policyVersion=envelope.versions.policy_version)
                if result.snapshot != expected:
                    raise ValueError('Result does not match frozen input')
                vacancy = VacancyRecord(owner_id=job.owner_id,
                    vacancy=envelope.request.vacancy.model_dump(mode='json'),
                    source_url=envelope.request.vacancy.url)
                s.add(vacancy); s.flush()
                analysis = AnalysisRecord(owner_id=job.owner_id, job_id=job.id, job_type='analysis',
                    vacancy_id=vacancy.id, profile_revision=int(envelope.request.profile_revision),
                    snapshot=encode_snapshot(result.snapshot), analysis=encode_analysis(result.analysis))
                s.add(analysis); s.flush()
                s.add(AnalysisAnnotation(owner_id=job.owner_id, analysis_id=analysis.id)); s.flush()
                _finish(s, job, metrics_environment=self.metrics_environment, status='succeeded')
                return analysis.id
        except _LostLease:
            return None

    def succeed_suggestions(self, lease, skills):
        if lease.type != 'skill_suggestions':
            raise ValueError('Invalid publication type')
        value = TypeAdapter(list[Skill]).validate_python(skills)
        if len(value) > 10:
            raise ValueError('Too many suggestions')
        try:
            with job_transaction(self.engine) as s:
                job = self._fenced_job(s, lease)
                if job is None: return False
                _finish(s, job, metrics_environment=self.metrics_environment, status='succeeded', output={'skills':value})
                return True
        except _LostLease:
            return False

    def fail(self, lease, error):
        try:
            with job_transaction(self.engine) as s:
                job = self._fenced_job(s, lease)
                if job is None: return False
                s.execute(update(ProviderCall).where(ProviderCall.job_id == job.id,
                    ProviderCall.execution_token == lease.execution_token,ProviderCall.state == 'started')
                    .values(state='unknown',error_code='execution_failed',finished_at=db_now(s)))
                _finish(s, job, metrics_environment=self.metrics_environment, status='failed', error=error.model_dump(mode='json'))
                return True
        except _LostLease:
            return False
