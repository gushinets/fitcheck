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
    def __init__(self, engine, *, policy=None, clock=None):
        from ..quotas.policy import QuotaPolicy
        from ..config import Settings
        self.engine = engine
        self.clock=clock
        self.policy = policy or QuotaPolicy.from_settings(Settings())

    def start(self, attempt: ProviderAttempt, *, bounds) -> UUID:
        from .budget_repository import BudgetRepository, BudgetWindowChanged
        from ..quotas.errors import QuotaError
        # A blocked daily-window lock can straddle midnight. Restart the whole
        # transaction so new windows preserve the global lock ordering.
        for _ in range(3):
            try:
                with unit_of_work(self.engine) as session:
                    clock=self.clock or (lambda: session.scalar(select(func.clock_timestamp())))
                    return BudgetRepository(session).reserve(attempt,bounds,policy=self.policy,now=clock(),clock=clock)
            except BudgetWindowChanged:
                continue
        raise QuotaError('budget_exceeded')

    def finish(self, call_id: UUID, *, state: str, input_tokens: int | None,
            output_tokens: int | None, cost: Decimal | None, currency: str | None,
            latency_ms: int, error_code: str | None, cached_input_tokens: int | None = None,
            cache_write_tokens: int | None = None, reasoning_tokens: int | None = None,
            cost_basis: str | None = None, rate_version: str | None = None,
            cost_reason: str | None = None, service_tier: str | None = None,
            processing_region: str | None = None, response_model: str | None = None) -> None:
        if state not in {'succeeded', 'failed', 'unknown'}:
            raise ValueError('Invalid final state')
        with unit_of_work(self.engine) as session:
            from .budget_repository import BudgetRepository
            from ..llm.types import ProviderReply
            candidate=session.get(ProviderCall,call_id)
            if candidate is None:raise ValueError('Provider call not found')
            if candidate.owner_id is not None:
                session.scalar(select(Owner).where(Owner.id==candidate.owner_id).with_for_update())
            if candidate.job_id is not None:
                session.scalar(select(Job).where(Job.id==candidate.job_id).with_for_update())
            # The initial read may predate a wait behind recovery or claim.
            # Coordinating owner/job locks are held now; refresh before settling.
            session.refresh(candidate)
            # Recovery's unknown rows retain their reservation even if a late reply arrives.
            effective_state='unknown' if candidate.state=='unknown' else state
            BudgetRepository(session).settle(call_id,reply=ProviderReply('',input_tokens,output_tokens,cost,currency,
                cached_input_tokens,cache_write_tokens,reasoning_tokens,cost_basis,rate_version,cost_reason,
                service_tier,processing_region,response_model),outcome=effective_state,now=utcnow())
            row = session.scalar(select(ProviderCall).where(ProviderCall.id == call_id).with_for_update().execution_options(populate_existing=True))
            if row is None:
                raise ValueError('Provider call not found')
            if row.state == 'unknown' and row.error_code == 'process_lost':
                return
            row.state, row.input_tokens, row.output_tokens = state, input_tokens, output_tokens
            row.cost, row.currency, row.latency_ms = cost, currency, latency_ms
            row.cached_input_tokens, row.cache_write_tokens = cached_input_tokens, cache_write_tokens
            row.reasoning_tokens, row.cost_basis = reasoning_tokens, cost_basis
            row.rate_version, row.cost_reason = rate_version, cost_reason
            row.service_tier, row.processing_region, row.response_model = service_tier, processing_region, response_model
            row.error_code, row.finished_at = error_code, utcnow()
