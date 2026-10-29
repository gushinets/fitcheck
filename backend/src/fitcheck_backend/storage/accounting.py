from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedMixin, IdentityMixin, OwnedMixin, UTCDateTime, utcnow


class QuotaBucket(OwnedMixin, IdentityMixin, Base):
    __tablename__ = "quota_buckets"
    policy_key: Mapped[str] = mapped_column(String(120))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    resets_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    limit: Mapped[int | None] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("id", "owner_id"), UniqueConstraint("owner_id", "policy_key", "window_start"),
                      CheckConstraint('"limit" >= 0 AND reserved >= 0 AND consumed >= 0 AND reserved+consumed <= "limit"', name="capacity"))


class QuotaReservation(OwnedMixin, CreatedMixin, IdentityMixin, Base):
    __tablename__ = "quota_reservations"
    job_id: Mapped[UUID]
    bucket_id: Mapped[UUID]
    units: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint("job_id", "bucket_id"),
        ForeignKeyConstraint(["job_id", "owner_id"], ["jobs.id", "jobs.owner_id"], deferrable=True, initially="IMMEDIATE", ondelete="CASCADE"),
        ForeignKeyConstraint(["bucket_id", "owner_id"], ["quota_buckets.id", "quota_buckets.owner_id"], deferrable=True, initially="IMMEDIATE", ondelete="CASCADE"),
        CheckConstraint("units > 0 AND status IN ('reserved','consumed','released')", name="state"),
    )


class ProviderCall(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "provider_calls"
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("owners.id", ondelete="SET NULL"))
    job_id: Mapped[UUID | None]
    # Logical operation identity survives technical job retention; no job FK.
    operation_id: Mapped[UUID | None]
    request_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    provider: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(200))
    attempt: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_basis: Mapped[str | None] = mapped_column(String(20))
    rate_version: Mapped[str | None] = mapped_column(String(120))
    cost_reason: Mapped[str | None] = mapped_column(String(80))
    service_tier: Mapped[str | None] = mapped_column(String(40))
    processing_region: Mapped[str | None] = mapped_column(String(40))
    response_model: Mapped[str | None] = mapped_column(String(200))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    currency: Mapped[str | None] = mapped_column(String(3))
    error_code: Mapped[str | None] = mapped_column(String(120))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    schema_version: Mapped[str | None] = mapped_column(String(120))
    policy_version: Mapped[str | None] = mapped_column(String(120))
    semantic_attempt: Mapped[int | None] = mapped_column(Integer)
    transport_attempt: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    execution_token: Mapped[UUID | None]
    __table_args__ = (
        CheckConstraint("cached_input_tokens>=0 AND cache_write_tokens>=0 AND reasoning_tokens>=0 AND coalesce(cached_input_tokens,0)+coalesce(cache_write_tokens,0)<=input_tokens AND reasoning_tokens<=output_tokens", name="usage_details"),
        CheckConstraint("cost_basis IS NULL OR (cost_basis IN ('unknown','estimated','reported') AND (cost IS NULL)=(cost_basis='unknown'))", name="cost_basis"),
        ForeignKeyConstraint(["job_id", "owner_id"], ["jobs.id", "jobs.owner_id"], deferrable=True, initially="IMMEDIATE"),
        CheckConstraint("job_id IS NULL OR owner_id IS NOT NULL", name="job_owner"),
        CheckConstraint("owner_id IS NOT NULL OR (job_id IS NULL AND request_key IS NULL)", name="anonymous"),
        CheckConstraint("owner_id IS NOT NULL OR operation_id IS NULL", name="operation_owner"),
        CheckConstraint("job_id IS NULL OR operation_id IS NULL OR operation_id=job_id", name="job_operation"),
        CheckConstraint("attempt >= 1 AND state IN ('started','succeeded','failed','unknown')", name="state"),
        CheckConstraint("semantic_attempt >= 1 AND transport_attempt >= 1 AND latency_ms >= 0", name="attempt_metadata"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND cost >= 0", name="usage"),
        CheckConstraint("(cost IS NULL) = (currency IS NULL) AND (currency IS NULL OR currency IN ('USD','EUR','RUB'))", name="currency"),
        Index("ix_provider_calls_owner_job", "owner_id", "job_id", "created_at"),
        Index("ix_provider_calls_execution", "job_id", "execution_token", "state"),
    )
