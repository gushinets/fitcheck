from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select, func

from .base import utcnow
from .database import unit_of_work
from .models import Job, Owner, ProviderCall


@dataclass(frozen=True)
class ProviderAttempt:
    owner_id: UUID
    job_id: UUID | None
    operation_id: UUID
    physical_attempt: int
    semantic_attempt: int
    transport_attempt: int
    operation: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    policy_version: str
    execution_token: UUID | None = None


class ProviderLedger:
    def __init__(self, engine):
        self.engine = engine

    def start(self, attempt: ProviderAttempt) -> UUID:
        with unit_of_work(self.engine) as session:
            if session.get(Owner, attempt.owner_id) is None:
                raise ValueError('Invalid owner ownership')
            if attempt.job_id is not None:
                job = session.scalar(select(Job).where(Job.id == attempt.job_id).with_for_update())
                if job is None or job.owner_id != attempt.owner_id:
                    raise ValueError('Invalid job ownership')
                if attempt.execution_token is not None:
                    now = session.scalar(select(func.clock_timestamp()))
                    if (job.status != 'running' or job.lease_token != attempt.execution_token
                            or job.lease_expires_at is None or job.lease_expires_at <= now):
                        raise ValueError('Invalid execution lease')
            row = ProviderCall(owner_id=attempt.owner_id, job_id=attempt.job_id,
                request_key=f'{attempt.operation_id}:{attempt.physical_attempt}',
                provider=attempt.provider, model=attempt.model, operation=attempt.operation,
                attempt=attempt.physical_attempt, semantic_attempt=attempt.semantic_attempt,
                transport_attempt=attempt.transport_attempt, prompt_version=attempt.prompt_version,
                schema_version=attempt.schema_version, policy_version=attempt.policy_version,
                execution_token=attempt.execution_token, state='started')
            session.add(row); session.flush()
            return row.id

    def finish(self, call_id: UUID, *, state: str, input_tokens: int | None,
            output_tokens: int | None, cost: Decimal | None, currency: str | None,
            latency_ms: int, error_code: str | None) -> None:
        if state not in {'succeeded', 'failed', 'unknown'}:
            raise ValueError('Invalid final state')
        with unit_of_work(self.engine) as session:
            row = session.scalar(select(ProviderCall).where(ProviderCall.id == call_id).with_for_update())
            if row is None:
                raise ValueError('Provider call not found')
            if row.state == 'unknown' and row.error_code == 'process_lost':
                return
            row.state, row.input_tokens, row.output_tokens = state, input_tokens, output_tokens
            row.cost, row.currency, row.latency_ms = cost, currency, latency_ms
            row.error_code, row.finished_at = error_code, utcnow()
