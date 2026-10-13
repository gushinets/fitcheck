from pydantic import TypeAdapter
from sqlalchemy import update
from ..contracts.domain import Skill
from ..contracts.resources import AnalysisSnapshot
from ..jobs.envelope import decode_envelope, AnalysisEnvelope
from .models import VacancyRecord, AnalysisRecord, AnalysisAnnotation, ProviderCall
from .payloads import encode_analysis, encode_snapshot
from .job_queue import job_transaction, fenced_job, db_now


class _LostLease(Exception):
    pass


def _finish(session, job, *, status, output=None, error=None):
    now = db_now(session)
    if job.lease_expires_at <= now:
        raise _LostLease()
    job.status, job.finished_at = status, now
    job.output, job.error = output, error
    job.lease_token, job.lease_expires_at = None, None


class JobPublication:
    def __init__(self, engine):
        self.engine = engine

    def succeed_analysis(self, lease, result):
        if lease.type != 'analysis':
            raise ValueError('Invalid publication type')
        try:
            with job_transaction(self.engine) as s:
                job = fenced_job(s, lease)
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
                _finish(s, job, status='succeeded')
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
                job = fenced_job(s, lease)
                if job is None: return False
                _finish(s, job, status='succeeded', output={'skills':value})
                return True
        except _LostLease:
            return False

    def fail(self, lease, error):
        try:
            with job_transaction(self.engine) as s:
                job = fenced_job(s, lease)
                if job is None: return False
                s.execute(update(ProviderCall).where(ProviderCall.job_id == job.id,
                    ProviderCall.execution_token == lease.execution_token,ProviderCall.state == 'started')
                    .values(state='unknown',error_code='execution_failed',finished_at=db_now(s)))
                _finish(s, job, status='failed', error=error.model_dump(mode='json'))
                return True
        except _LostLease:
            return False
