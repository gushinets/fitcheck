"""Aggregate report contract and private, content-free snapshot projections."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, kw_only=True)
class ReportOptions:
    start: datetime
    end: datetime
    timezone: str = 'Europe/Moscow'
    environment: str
    population: str

    def __post_init__(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.start, self.end)):
            raise ValueError('Report dates require an explicit UTC offset')
        object.__setattr__(self, 'start', self.start.astimezone(dt_timezone.utc))
        object.__setattr__(self, 'end', self.end.astimezone(dt_timezone.utc))
        if not timedelta(0) < self.end-self.start <= timedelta(days=366):
            raise ValueError('Report range must be positive and at most 366 days')
        if self.environment not in {'development', 'production', 'test'}:
            raise ValueError('Invalid report environment')
        if self.population not in {'visitor', 'account', 'all'}:
            raise ValueError('Population must be visitor, account or all')
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError('Invalid report timezone') from None


@dataclass(frozen=True)
class MetricRow:
    metric: str
    dimensions: dict[str, str] = field(default_factory=dict)
    value: float | int | Decimal | None = None
    numerator: float | int | Decimal | None = None
    denominator: float | int | None = None
    sample_count: int | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    reason: str | None = None
    data_start: datetime | None = None


def serializable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, dict):
        return {key: serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    return value


@dataclass(frozen=True)
class MetricReport:
    options: ReportOptions
    rows: list[MetricRow]

    def to_json(self) -> dict:
        return serializable({'period': asdict(self.options), 'rows': [asdict(row) for row in self.rows]})


@dataclass(frozen=True, kw_only=True)
class Event:
    name: str
    occurred_at: datetime
    source: str
    subject_kind: str
    subject_id: UUID | None
    session_id: UUID | None = None
    operation_id: UUID | None = None
    domain_key: str | None = None
    properties: dict = field(default_factory=dict)
    event_id: UUID | None = None
    received_at: datetime | None = None
    submitted_occurred_at: datetime | None = None
    clock_adjusted: bool = False


@dataclass(frozen=True, kw_only=True)
class Attempt:
    call_id: UUID
    operation_id: UUID | None
    subject_id: UUID | None
    source: str
    purpose: str
    provider: str
    model: str
    started_at: datetime
    state: str
    finished_at: datetime | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost: Decimal | None = None
    currency: str | None = None
    cost_basis: str = 'unknown'
    rate_version: str | None = None
    cost_reason: str | None = None
    service_tier: str | None = None
    processing_region: str | None = None
    response_model: str | None = None
    error_code: str | None = None
    execution_token: UUID | None = None


@dataclass(kw_only=True)
class Operation:
    operation_id: UUID
    subject_id: UUID | None
    source: str
    kind: str
    created_at: datetime | None
    state: str = 'unknown'
    finished_at: datetime | None = None
    started_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    executions: int = 0
    recovered: bool = False
    provenance: str = ''


@dataclass(frozen=True, kw_only=True)
class AnalysisFact:
    analysis_id: UUID
    owner_id: UUID
    job_id: UUID | None
    created_at: datetime
    finished_at: datetime | None
    state: str | None
    account_owned: bool
    mode: str | None
    predicted_score: int | None
    corrected_score: int | None
    feedback_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class DemoProof:
    guest_owner_id: UUID
    job_id: UUID | None
    result_id: UUID | None


@dataclass
class Snapshot:
    missing_domain_registration_facts: int = 0
    server_backed: bool = False
    snapshot_at: datetime | None = None
    identities: dict = field(default_factory=dict)
    demo_proofs: dict[UUID, DemoProof] = field(default_factory=dict)
    analyses: list[AnalysisFact] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    collection_interruptions: list[dict] = field(default_factory=list)
    collections: dict[str, datetime] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)
    backend_scope_reason: str | None = 'Backend database environment scope is not configured'
    history_floor: datetime | None = None
    backfill_complete_through: datetime | None = None
    retention_floors: dict[str, datetime] = field(default_factory=dict)
