from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, UTCDateTime

ENVIRONMENTS = "environment IN ('development','production','test')"
SOURCES = "source IN ('website_client','website_server','backend_server','reconstructed_backend')"


class MetricJournal(Base):
    __tablename__ = 'metric_journal'
    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30))
    environment: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    subject_kind: Mapped[str] = mapped_column(String(10))
    subject_id: Mapped[UUID | None]
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey('owners.id', ondelete='CASCADE'))
    session_id: Mapped[UUID | None]
    operation_id: Mapped[UUID | None]
    domain_key: Mapped[str | None] = mapped_column(String(120))
    properties: Mapped[dict] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    clock_adjusted: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (
        UniqueConstraint('environment', 'subject_id', 'domain_key', name='uq_metric_domain_transition'),
        CheckConstraint(ENVIRONMENTS, name='environment'), CheckConstraint(SOURCES, name='source'),
        CheckConstraint("schema_version=1 AND subject_kind IN ('visitor','account','anonymous')", name='identity'),
        CheckConstraint("jsonb_typeof(properties)='object' AND payload_hash ~ '^[0-9a-f]{64}$'", name='payload'),
        CheckConstraint("(subject_kind='account' AND subject_id IS NOT NULL AND owner_id IS NOT NULL AND owner_id=subject_id) OR (subject_kind='visitor' AND subject_id IS NOT NULL AND owner_id IS NULL) OR (subject_kind='anonymous' AND subject_id IS NULL AND owner_id IS NULL AND name='account_deleted' AND source='backend_server' AND session_id IS NULL AND operation_id IS NULL AND domain_key IS NULL AND properties='{}'::jsonb)", name='owner'),
        Index('ix_metric_journal_retention', 'received_at', 'event_id'),
        Index('ix_metric_journal_period', 'environment', 'occurred_at', 'name'),
        Index('ix_metric_journal_source_period', 'environment', 'source', 'occurred_at'),
        Index('ix_metric_journal_subject', 'environment', 'subject_kind', 'subject_id', 'occurred_at'),
    )


class WebsiteProviderAttempt(Base):
    __tablename__ = 'website_provider_attempts'
    call_id: Mapped[UUID] = mapped_column(primary_key=True)
    operation_id: Mapped[UUID]
    subject_id: Mapped[UUID]
    environment: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(40))
    ordinal: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(120))
    policy_version: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    state: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    currency: Mapped[str | None] = mapped_column(String(3))
    cost_basis: Mapped[str] = mapped_column(String(20))
    rate_version: Mapped[str | None] = mapped_column(String(120))
    __table_args__ = (
        CheckConstraint(ENVIRONMENTS, name='environment'),
        CheckConstraint("provider IN ('openai','deepseek') AND purpose IN ('analysis.generate','analysis.audit','skills.generate')", name='provider'),
        CheckConstraint("ordinal BETWEEN 1 AND 8 AND state IN ('started','succeeded','failed','unknown')", name='state'),
        CheckConstraint("(state='started')=(finished_at IS NULL) AND (finished_at IS NULL OR finished_at>=started_at)", name='settled'),
        CheckConstraint("input_tokens>=0 AND output_tokens>=0 AND cached_input_tokens>=0 AND cache_write_tokens>=0 AND reasoning_tokens>=0 AND cost>=0", name='usage'),
        CheckConstraint("(cost IS NULL)=(currency IS NULL) AND (cost IS NULL)=(cost_basis='unknown') AND cost_basis IN ('unknown','estimated','reported') AND (currency IS NULL OR currency IN ('USD','EUR','RUB'))", name='cost'),
        Index('ix_website_attempts_period', 'environment', 'started_at'),
        Index('ix_website_attempts_operation', 'environment', 'operation_id'),
    )


class MetricCollection(Base):
    __tablename__ = 'metric_collections'
    source: Mapped[str] = mapped_column(String(30), primary_key=True)
    environment: Mapped[str] = mapped_column(String(20), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    available_from: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint(ENVIRONMENTS, name='environment'), CheckConstraint(SOURCES, name='source'))


class MetricErasedVisitor(Base):
    __tablename__ = 'metric_erased_visitors'
    environment: Mapped[str] = mapped_column(String(20), primary_key=True)
    visitor_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    erased_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint(ENVIRONMENTS, name='environment'),
        CheckConstraint("visitor_digest ~ '^[0-9a-f]{64}$'", name='digest'),
        Index('ix_metric_erased_visitors_expiry', 'erased_at'))
