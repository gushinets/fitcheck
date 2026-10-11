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
    limit: Mapped[int] = mapped_column(Integer)
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
    request_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    provider: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(200))
    attempt: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    currency: Mapped[str | None] = mapped_column(String(3))
    error_code: Mapped[str | None] = mapped_column(String(120))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "owner_id"], ["jobs.id", "jobs.owner_id"], deferrable=True, initially="IMMEDIATE"),
        CheckConstraint("job_id IS NULL OR owner_id IS NOT NULL", name="job_owner"),
        CheckConstraint("owner_id IS NOT NULL OR (job_id IS NULL AND request_key IS NULL)", name="anonymous"),
        CheckConstraint("attempt >= 1 AND state IN ('started','succeeded','failed','unknown')", name="state"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND cost >= 0", name="usage"),
        CheckConstraint("(cost IS NULL) = (currency IS NULL) AND (currency IS NULL OR currency IN ('USD','EUR','RUB'))", name="currency"),
        Index("ix_provider_calls_owner_job", "owner_id", "job_id", "created_at"),
    )
