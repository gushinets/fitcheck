import time
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from .types import OperationContext, CallBudget
from .policy import ProviderPolicy
from ..storage.models import Owner, Job


def verify_owner_job(session: Session, owner_id: UUID, job_id: UUID | None, job_type: str):
    if session.get(Owner, owner_id) is None:
        raise ValueError('Owner not found')
    if job_id is not None:
        job = session.get(Job, job_id)
        if job is None or job.owner_id != owner_id or job.type != job_type:
            raise ValueError('Invalid job ownership or type')


def operation_context(owner_id: UUID, job_id: UUID | None, policy: ProviderPolicy) -> OperationContext:
    return OperationContext(owner_id, job_id, uuid4(), policy,
        CallBudget(policy.max_calls, time.monotonic()+policy.deadline_seconds, time.monotonic))
