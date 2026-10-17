from uuid import UUID
from sqlalchemy import select, func, text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError
from ..contracts.resources import AccountAnalysisStart, SkillSuggestionStart
from ..storage.database import unit_of_work
from ..storage.models import Owner, User, Job, AnalysisRecord
from ..storage.payloads import decode_snapshot, canonical_hash
from ..auth.service import active_session
from ..auth.access import require_verified
from ..storage.auth_repository import AuthRepository
from ..storage.job_repository import request_digest
from ..storage.profile_repository import get_profile
from ..storage.calibration_repository import get_calibration
from .envelope import AnalysisEnvelope, SuggestionsEnvelope, execution_versions
from .types import AdmissionResult
from .errors import JobError
from ..metrics.lifecycle import append_domain_event, job_key


class JobAdmission:
    def __init__(self, engine, limiter, *, model='gpt-6-luna', metrics_environment=None):
        from ..llm.policy import resolve_model
        self.model = resolve_model(model)
        self.engine, self.limiter = engine, limiter
        self.metrics_environment = metrics_environment

    def start_analysis(self, *, owner_id: UUID, request: AccountAnalysisStart,
            idempotency_key: str, client_ip: str) -> AdmissionResult:
        return self._start(owner_id, 'analysis', request, idempotency_key, client_ip)

    def start_suggestions(self, *, owner_id: UUID, request: SkillSuggestionStart,
            idempotency_key: str, client_ip: str) -> AdmissionResult:
        return self._start(owner_id, 'skill_suggestions', request, idempotency_key, client_ip)

    def reanalyze(self, *, principal, analysis_id, idempotency_key, client_ip, clock):
        require_verified(principal)
        return self._start(principal.owner_id, 'analysis', None, idempotency_key, client_ip,
            analysis_id=analysis_id, principal=principal, clock=clock)

    def _start(self, owner_id, kind, request, key, ip, *, analysis_id=None, principal=None, clock=None):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise JobError('invalid_request')
        dto = AccountAnalysisStart if kind == 'analysis' else SkillSuggestionStart
        try:
            if analysis_id is None:
                request = dto.model_validate(request.model_dump(mode='json', by_alias=True))
                payload = request.model_dump(mode='json', by_alias=True)
            digest = (canonical_hash({'operation': 'reanalyze', 'analysisId': str(analysis_id)})
                if analysis_id is not None else request_digest(kind, payload))
            with unit_of_work(self.engine) as s:
                s.execute(text("SET LOCAL statement_timeout='5s'"))
                s.execute(text("SET LOCAL lock_timeout='3s'"))
                owner = s.scalar(select(Owner).where(Owner.id == owner_id).with_for_update())
                if owner is None or owner.kind != 'user':
                    raise JobError('forbidden')
                user = s.scalar(select(User).where(User.owner_id == owner_id).with_for_update())
                if user is None or user.email_verified_at is None:
                    raise JobError('forbidden')
                if principal is not None:
                    if user.id != principal.user_id:
                        raise JobError('forbidden')
                    active_session(AuthRepository(s), principal, clock())
                existing = s.scalar(select(Job).where(Job.owner_id == owner_id,
                    Job.type == kind, Job.idempotency_key == key))
                if existing is not None:
                    if existing.request_hash != digest:
                        raise JobError('conflict')
                    return AdmissionResult(existing.id, existing.type, existing.status)
                if analysis_id is not None:
                    original = s.scalar(select(AnalysisRecord).where(
                        AnalysisRecord.id == analysis_id, AnalysisRecord.owner_id == owner_id))
                    if original is None:
                        raise JobError('not_found')
                    snapshot = decode_snapshot(original.snapshot)
                    current = get_profile(s, owner_id)
                    if current is None:
                        raise JobError('not_found')
                    request = AccountAnalysisStart(mode='account', vacancy=snapshot.vacancy,
                        profileRevision=current.revision, locale=snapshot.locale)
                active = s.scalar(select(func.count()).select_from(Job).where(
                    Job.owner_id == owner_id, Job.type.in_(['analysis','skill_suggestions']),
                    Job.status.in_(['queued','running'])))
                if active >= 2:
                    raise JobError('rate_limited')
                self.limiter.enforce('jobs', {'user': str(user.id), 'ip': ip})
                if kind == 'analysis':
                    revision = int(request.profile_revision)
                    if not 1 <= revision <= 2_147_483_647:
                        raise JobError('invalid_request')
                    profile = get_profile(s, owner_id, revision)
                    if profile is None:
                        raise JobError('not_found')
                    envelope = AnalysisEnvelope(envelopeVersion=1, request=request,
                        profile=profile.profile, memory=get_calibration(s, owner_id),
                        versions=execution_versions(kind, model=self.model))
                else:
                    envelope = SuggestionsEnvelope(envelopeVersion=1, request=request,
                        versions=execution_versions(kind, model=self.model))
                job = Job(owner_id=owner_id, type=kind, idempotency_key=key,
                    request_hash=digest, input=envelope.model_dump(mode='json', by_alias=True))
                s.add(job); s.flush()
                append_domain_event(s, name="job_admitted", owner_id=job.owner_id,
                    domain_key=job_key(job.id,"admitted"), occurred_at=job.created_at,
                    properties={"jobType":job.type}, environment=self.metrics_environment)
                return AdmissionResult(job.id, job.type, job.status)
        except (SQLAlchemyError, ValidationError, ValueError):
            raise JobError('service_unavailable') from None
