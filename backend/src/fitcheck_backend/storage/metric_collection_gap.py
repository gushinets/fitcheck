"""Identity-free evidence that a runtime intentionally omitted telemetry."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, UTCDateTime
from .metrics import ENVIRONMENTS, SOURCES


class MetricCollectionGap(Base):
    __tablename__ = 'metric_collection_gaps'
    id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    environment: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (
        CheckConstraint(ENVIRONMENTS, name='environment'),
        CheckConstraint(SOURCES, name='source'),
        CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name='interval'),
        Index('ix_metric_collection_gaps_scope', 'environment', 'source', 'started_at'),
        Index('ix_metric_collection_gaps_retention', 'ended_at', 'id'),
    )
