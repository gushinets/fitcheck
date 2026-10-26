"""Authoritative facts appended inside the caller's domain transaction."""
from uuid import uuid4
from sqlalchemy import delete, select
from ..storage.base import utcnow
from ..storage.models import User, Guest
from ..storage.metrics import MetricJournal
from .contracts import MetricEvent
from .repository import MetricRepository


def append_domain_event(session, *, name, owner_id, domain_key, occurred_at,
                        properties, environment, source='backend_server') -> None:
    if environment is None:
        return
    # Guest ownership is not a registered backend account.
    if session.scalar(select(User.id).where(User.owner_id == owner_id)) is None:
        return
    event = MetricEvent(eventId=uuid4(), name=name, subjectKind='account',
        subjectId=owner_id, domainKey=domain_key, occurredAt=occurred_at, properties=properties)
    MetricRepository(session).append(event, source=source, environment=environment, received_at=utcnow())


def registration_key(owner_id):
    return f'account:{owner_id}:registered'


def verification_key(owner_id):
    return f'account:{owner_id}:verified'


def profile_key(owner_id, revision):
    return f'profile:{owner_id}:revision:{revision}'


def job_key(job_id, transition, execution_token=None):
    return f'job:{job_id}:{transition}' + (f':{execution_token}' if execution_token else '')


def job_properties(job):
    return {'jobType':job.type, 'attempts':min(job.attempts, 2)}


def terminal_properties(job):
    properties = job_properties(job) | {
        'outcome':job.status,
        'durationMs':max(0, min(86_400_000, int((job.finished_at-job.created_at).total_seconds()*1000))),
    }
    # Existing safe domain codes are independently validated by the registry.
    if job.status == 'failed':
        from .registry import SafeCode
        from pydantic import TypeAdapter, ValidationError
        try:
            properties['errorCode'] = TypeAdapter(SafeCode).validate_python((job.error or {}).get('code'))
        except ValidationError:
            properties['errorCode'] = 'service_unavailable'
    return properties


def append_job_finished(session, job, environment):
    append_domain_event(session, name='job_finished', owner_id=job.owner_id,
        domain_key=job_key(job.id,'finished'), occurred_at=job.finished_at,
        properties=terminal_properties(job), environment=environment)


def erase_account_metrics(session, owner_id) -> None:
    user_id = session.scalar(select(User.id).where(User.owner_id==owner_id))
    guest_ids = list(session.scalars(select(Guest.owner_id).where(Guest.claimed_by_user_id==user_id))) if user_id else []
    session.execute(delete(MetricJournal).where(MetricJournal.owner_id.in_([owner_id, *guest_ids])))


def append_account_deleted(session, *, environment, occurred_at):
    if environment is None:
        return
    MetricRepository(session).append(MetricEvent(eventId=uuid4(), name='account_deleted',
        subjectKind='anonymous', subjectId=None, occurredAt=occurred_at),
        source='backend_server', environment=environment, received_at=utcnow())
