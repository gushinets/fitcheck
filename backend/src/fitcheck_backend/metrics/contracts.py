from datetime import datetime, UTC
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, field_validator, model_validator
from ..contracts.domain import DTO
from .registry import REGISTRY, WEBSITE_SERVER, ModelName, SafeCode, Version

# Reserved storage marker: no live visitor may claim an erased association.
ERASED_VISITOR_ID = UUID(int=0)

Environment = Literal['development', 'production', 'test']
Source = Literal['website_client', 'website_server', 'backend_server', 'reconstructed_backend']
TokenCount = Annotated[StrictInt, Field(ge=0, le=100_000_000)]


def utc(value):
    if value is not None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Expected timezone-aware timestamp')
        return value.astimezone(UTC)
    return None


class MetricEvent(DTO):
    event_id: UUID
    name: SafeCode
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)] = 1
    occurred_at: datetime
    subject_id: UUID | None
    subject_kind: Literal['visitor', 'account', 'anonymous'] = 'visitor'
    session_id: UUID | None = None
    operation_id: UUID | None = None
    domain_key: Version | None = None
    properties: dict = Field(default_factory=dict)

    _utc = field_validator('occurred_at')(utc)

    @model_validator(mode='after')
    def valid_properties(self):
        if self.subject_kind == 'anonymous':
            if (self.name != 'account_deleted' or self.subject_id is not None or self.session_id is not None
                    or self.operation_id is not None or self.domain_key is not None or self.properties):
                raise ValueError('Invalid anonymous deletion fact')
        elif self.subject_id is None:
            raise ValueError('Subject identifier required')
        if self.subject_kind == 'visitor' and self.subject_id == ERASED_VISITOR_ID:
            raise ValueError('Reserved visitor identifier')
        kind = REGISTRY.get(self.name)
        if kind is None:
            raise ValueError('Unsupported event name')
        if self.name in WEBSITE_SERVER and self.operation_id is None:
            raise ValueError('Website terminal event requires operation ID')
        self.properties = kind.model_validate(self.properties).model_dump(mode='json', exclude_none=True)
        return self


class WebsiteAttempt(DTO):
    call_id: UUID
    operation_id: UUID
    subject_id: UUID
    purpose: Literal['analysis.generate', 'analysis.audit', 'skills.generate']
    ordinal: Annotated[StrictInt, Field(ge=1, le=8)]
    provider: Literal['openai', 'deepseek']
    model: ModelName
    prompt_version: Version
    policy_version: Version
    started_at: datetime
    finished_at: datetime | None = None
    state: Literal['started', 'succeeded', 'failed', 'unknown']
    error_code: SafeCode | None = None
    input_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None
    cached_input_tokens: TokenCount | None = None
    cache_write_tokens: TokenCount | None = None
    reasoning_tokens: TokenCount | None = None
    cost: Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=8, allow_inf_nan=False)] | None = None
    currency: Literal['USD', 'EUR', 'RUB'] | None = None
    cost_basis: Literal['unknown', 'estimated', 'reported'] = 'unknown'
    rate_version: Version | None = None

    _utc = field_validator('started_at', 'finished_at')(utc)

    @field_validator('subject_id')
    @classmethod
    def live_visitor(cls, value):
        if value == ERASED_VISITOR_ID:
            raise ValueError('Reserved visitor identifier')
        return value

    @model_validator(mode='after')
    def valid_settlement(self):
        if (self.state == 'started') != (self.finished_at is None):
            raise ValueError('Invalid attempt settlement')
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError('Invalid attempt duration')
        if (self.cost is None) != (self.currency is None) or (self.cost is None) != (self.cost_basis == 'unknown'):
            raise ValueError('Invalid cost coverage')
        if self.state == 'started' and any(value is not None for value in (
                self.input_tokens, self.output_tokens, self.cost, self.error_code,
                self.cached_input_tokens, self.cache_write_tokens, self.reasoning_tokens)):
            raise ValueError('Started attempt cannot declare usage')
        cached = (self.cached_input_tokens or 0) + (self.cache_write_tokens or 0)
        if self.input_tokens is not None and cached > self.input_tokens:
            raise ValueError('Invalid input token subdivision')
        if self.reasoning_tokens is not None and self.output_tokens is not None and self.reasoning_tokens > self.output_tokens:
            raise ValueError('Invalid output token subdivision')
        return self


class WebsiteBatch(DTO):
    source: Literal['website_client', 'website_server']
    events: list[MetricEvent] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def valid_source(self):
        from .registry import validate_event
        from .errors import MetricsError
        for event in self.events:
            try:
                validate_event(event, source=self.source)
            except MetricsError:
                raise ValueError('Invalid website event source or identity') from None
        return self


class AttemptBatch(DTO):
    source: Literal['website_server']
    attempts: list[WebsiteAttempt] = Field(min_length=1, max_length=20)


class IngestResult(DTO):
    accepted: int
    duplicates: int


class DeleteResult(DTO):
    deleted: int
