from uuid import UUID
from sqlalchemy import select, func, text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError
from ..contracts.resources import AccountAnalysisStart, GuestAnalysisStart, SkillSuggestionStart
from ..storage.database import unit_of_work
from ..storage.models import Owner, User, Job, AnalysisRecord, Preference
from ..storage.payloads import decode_snapshot, canonical_hash
from ..auth.service import active_session
from ..auth.access import require_verified
from ..storage.auth_repository import AuthRepository
from ..storage.job_repository import request_digest
from ..storage.profile_repository import get_profile,create_profile,update_profile
from ..storage.guest_repository import require_identity
from ..storage.quota_repository import QuotaRepository
from ..storage.base import utcnow
from ..quotas.policy import QuotaPolicy
from ..config import Settings
from ..storage.calibration_repository import get_calibration
from .envelope import AnalysisEnvelopeV2, SuggestionsEnvelopeV2, FrozenLimits, execution_versions
from .types import AdmissionResult
from .errors import JobError
from ..metrics.lifecycle import append_domain_event, job_key


class JobAdmission:
    def __init__(self, engine, limiter, *, model='gpt-6-luna', metrics_environment=None, policy=None, clock=utcnow):
        from ..llm.policy import resolve_model
        self.model = resolve_model(model)
        self.engine, self.limiter = engine, limiter
        self.metrics_environment = metrics_environment
        self.policy=policy or QuotaPolicy.from_settings(Settings())
        self.clock=clock

    def start_analysis(self, *, owner_id: UUID | None = None, identity=None, request: AccountAnalysisStart | GuestAnalysisStart,
            idempotency_key: str, client_ip: str) -> AdmissionResult:
        return self._start(identity.owner_id if identity else owner_id, 'analysis', request, idempotency_key, client_ip,identity=identity)

    def start_suggestions(self, *, owner_id: UUID | None = None, identity=None, request: SkillSuggestionStart,
            idempotency_key: str, client_ip: str) -> AdmissionResult:
        return self._start(identity.owner_id if identity else owner_id, 'skill_suggestions', request, idempotency_key, client_ip,identity=identity)

    def reanalyze(self, *, principal, analysis_id, idempotency_key, client_ip, clock):
        require_verified(principal)
        return self._start(principal.owner_id, 'analysis', None, idempotency_key, client_ip,
            analysis_id=analysis_id, principal=principal, clock=clock)

    def _start(self, owner_id, kind, request, key, ip, *, analysis_id=None, principal=None, clock=None, identity=None):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise JobError('invalid_request')
        mode=identity.mode if identity else 'account'
        if kind=='analysis' and request is not None and request.mode!=mode:raise JobError('forbidden')
        dto = (GuestAnalysisStart if mode=='guest' else AccountAnalysisStart) if kind == 'analysis' else SkillSuggestionStart
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
                if owner is None or owner.kind != ('guest' if mode=='guest' else 'user'):
                    raise JobError('forbidden')
                now=self.clock()
                user=None
                if identity is not None:require_identity(s,identity,now)
                if mode=='account':
                    user = s.scalar(select(User).where(User.owner_id == owner_id).with_for_update())
                    if user is None or user.email_verified_at is None:raise JobError('forbidden')
                    if principal is not None:
                        if user.id != principal.user_id:raise JobError('forbidden')
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
                    preferences=s.get(Preference,owner_id) if snapshot.locale is None else None
                    locale=snapshot.locale or (preferences.locale if preferences else 'en')
                    request = AccountAnalysisStart(mode='account', vacancy=snapshot.vacancy,
                        profileRevision=current.revision, locale=locale)
                active = s.scalar(select(func.count()).select_from(Job).where(
                    Job.owner_id == owner_id, Job.type.in_(['analysis','skill_suggestions','import']),
                    Job.status.in_(['queued','running'])))
                if active >= self.policy.limits(mode).max_active_jobs:
                    raise JobError('rate_limited')
                if mode=='guest':
                    self.limiter.enforce('guest_jobs',{'guest':str(owner_id),'ip':ip},rules=[('guest',5,60),('ip',30,900)])
                else:self.limiter.enforce('jobs', {'user': str(user.id), 'ip': ip})
                quotas=QuotaRepository(s)
                quotas.reap_extractions(now,owner_id=owner_id)
                operation='analysis' if kind=='analysis' else 'suggestions'
                limits=FrozenLimits(calls=getattr(self.policy,operation+'_calls'),tokens=getattr(self.policy,operation+'_tokens'),usd=getattr(self.policy,operation+'_usd'))
                if kind == 'analysis':
                    if mode=='guest':
                        current=get_profile(s,owner_id)
                        profile=(create_profile(s,owner_id,request.profile) if current is None else
                            update_profile(s,owner_id,int(current.revision),request.profile))
                    else:
                        revision = int(request.profile_revision)
                        if not 1 <= revision <= 2_147_483_647:raise JobError('invalid_request')
                        profile=get_profile(s,owner_id,revision)
                        if profile is None:raise JobError('not_found')
                    envelope=AnalysisEnvelopeV2(envelopeVersion=2,mode=mode,sessionId=identity.session_id if identity else None,
                        profileRevision=profile.revision,profile=profile.profile,vacancy=request.vacancy,locale=request.locale,
                        memory=[] if mode=='guest' else get_calibration(s,owner_id),limits=limits,
                        versions=execution_versions(kind,model=self.model))
                else:
                    envelope=SuggestionsEnvelopeV2(envelopeVersion=2,mode=mode,sessionId=identity.session_id if identity else None,
                        request=request,limits=limits,versions=execution_versions(kind,model=self.model))
                job = Job(owner_id=owner_id, type=kind, idempotency_key=key,
                    request_hash=digest, input=envelope.model_dump(mode='json', by_alias=True))
                s.add(job); s.flush()
                quotas.reserve_job(owner_id,job.id,operation,self.policy,now)
                append_domain_event(s, name="job_admitted", owner_id=job.owner_id,
                    domain_key=job_key(job.id,"admitted"), occurred_at=job.created_at,
                    properties={"jobType":job.type}, environment=self.metrics_environment)
                return AdmissionResult(job.id, job.type, job.status)
        except (SQLAlchemyError, ValidationError, ValueError):
            raise JobError('service_unavailable') from None
