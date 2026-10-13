import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable
from uuid import UUID
from .policy import ProviderPolicy
from .errors import LlmError


class CallBudget:
    def __init__(self, max_calls: int, deadline: float, clock: Callable[[], float]):
        self.max_calls, self.deadline, self.clock, self.calls = max_calls, deadline, clock, 0

    def remaining(self) -> float:
        remaining = self.deadline - self.clock()
        if not math.isfinite(remaining) or remaining <= 0:
            raise LlmError('timeout')
        return remaining

    def admit(self) -> tuple[int, float]:
        remaining = self.remaining()
        if self.calls >= self.max_calls:
            raise LlmError('invalid_output')
        self.calls += 1
        return self.calls, remaining


@dataclass(frozen=True)
class OperationContext:
    owner_id: UUID
    job_id: UUID | None
    operation_id: UUID
    policy: ProviderPolicy
    budget: CallBudget
    execution_token: UUID | None = None


@dataclass(frozen=True)
class ProviderReply:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    cost: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class GatewayReply:
    reply: ProviderReply
    call_id: UUID
    latency_ms: int
