from contextlib import contextmanager
from uuid import uuid4
from sqlalchemy import select,func
from sqlalchemy.exc import SQLAlchemyError
from ..storage.job_queue import job_transaction
from ..storage.models import Owner,Job
from ..storage.guest_repository import require_identity
from ..storage.quota_repository import QuotaRepository
from ..contracts.quotas import QuotaResource,OperationQuota
from ..auth.errors import AuthError


class QuotaService:
    def __init__(self,engine,policy,clock):self.engine,self.policy,self.clock=engine,policy,clock

    @contextmanager
    def transaction(self,identity,*,validate=True):
        try:
            with job_transaction(self.engine) as s:
                owner=s.scalar(select(Owner).where(Owner.id==identity.owner_id).with_for_update())
                if owner is None:raise AuthError('unauthenticated')
                if validate:require_identity(s,identity,self.clock())
                yield s,QuotaRepository(s)
        except SQLAlchemyError:raise AuthError('service_unavailable') from None

    def get(self,identity):
        with self.transaction(identity) as (s,repo):
            now=self.clock();repo.reap_extractions(now,owner_id=identity.owner_id)
            operations={}
            for operation in ('analysis','extraction','suggestions'):
                bucket=repo.bucket(identity.owner_id,operation,self.policy,now)
                limit=getattr(self.policy.account,operation) if identity.mode=='account' else bucket.limit
                operations[operation]=OperationQuota(limit=limit,remaining=None if limit is None else max(0,limit-bucket.reserved-bucket.consumed),
                    reserved=bucket.reserved,consumed=bucket.consumed)
            active=s.scalar(select(func.count()).select_from(Job).where(Job.owner_id==identity.owner_id,Job.status.in_(['queued','running'])))
            return QuotaResource(remaining=operations['analysis'].remaining,resetsAt=bucket.resets_at,
                mode=identity.mode,expiresAt=identity.expires_at if identity.mode=='guest' else None,
                registrationRequired=identity.mode=='guest' and operations['analysis'].remaining==0,
                activeJobs=active,maxActiveJobs=self.policy.limits(identity.mode).max_active_jobs,operations=operations)

    @contextmanager
    def extraction(self,identity):
        identifier=uuid4()
        with self.transaction(identity) as (s,repo):
            repo.reap_extractions(self.clock(),owner_id=identity.owner_id)
            repo.reserve_extraction(identity.owner_id,identifier,self.policy,self.clock())
        finished=False
        try:
            yield
            with self.transaction(identity) as (s,repo):
                if not repo.settle_extraction(identifier,success=True,now=self.clock()):raise AuthError('service_unavailable')
            finished=True
        finally:
            if not finished:
                with self.transaction(identity,validate=False) as (s,repo):
                    repo.settle_extraction(identifier,success=False,now=self.clock())
