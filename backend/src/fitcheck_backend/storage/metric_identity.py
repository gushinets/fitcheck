"""Confirmed identity evidence, separate from observed event populations."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, IdentityMixin, UTCDateTime
from .metrics import ENVIRONMENTS


class MetricIdentityTransition(IdentityMixin, Base):
    __tablename__='metric_identity_transitions'
    environment: Mapped[str] = mapped_column(String(20))
    visitor_id: Mapped[UUID]
    account_owner_id: Mapped[UUID | None] = mapped_column(ForeignKey('owners.id',ondelete='CASCADE'))
    guest_owner_id: Mapped[UUID | None] = mapped_column(ForeignKey('owners.id',ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(String(12))
    source_id: Mapped[UUID | None]
    auth_session_id: Mapped[UUID | None]
    cookie_issued_at: Mapped[datetime] = mapped_column(UTCDateTime)
    request_started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    anonymous_from: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_basis: Mapped[str | None] = mapped_column(String(12))
    __table_args__=(
        UniqueConstraint('environment','kind','source_id'),
        CheckConstraint(ENVIRONMENTS,name='environment'),
        CheckConstraint("kind IN ('registered','login','claim','erased')",name='kind'),
        CheckConstraint("(kind='claim')=(guest_owner_id IS NOT NULL)",name='guest'),
        CheckConstraint("(kind='erased' AND account_owner_id IS NULL AND source_id IS NULL AND auth_session_id IS NULL AND anonymous_from IS NULL) OR (kind!='erased' AND account_owner_id IS NOT NULL AND source_id IS NOT NULL AND auth_session_id IS NOT NULL)",name='identity'),
        CheckConstraint("(kind='claim')=(expires_at IS NULL)",name='expiry'),
        CheckConstraint("(ended_at IS NULL)=(end_basis IS NULL) AND (end_basis IS NULL OR end_basis IN ('revoked','expired'))",name='end'),
        CheckConstraint('cookie_issued_at<=occurred_at AND request_started_at<=occurred_at',name='time'),
        Index('ix_metric_identity_visitor','environment','visitor_id','occurred_at'),
        Index('ix_metric_identity_session','auth_session_id'),
        Index('ix_metric_identity_retention','occurred_at','id'),
    )


class MetricVisitorBoundary(Base):
    """No account identifiers: erasure cannot donate old history to a new account."""
    __tablename__='metric_visitor_boundaries'
    environment: Mapped[str] = mapped_column(String(20),primary_key=True)
    visitor_id: Mapped[UUID] = mapped_column(primary_key=True)
    anonymous_floor: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__=(CheckConstraint(ENVIRONMENTS,name='environment'),
                   Index('ix_metric_visitor_boundary_retention','anonymous_floor'))
