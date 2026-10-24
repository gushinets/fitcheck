"""Minimal successful operation evidence; deleted with its saved analysis."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, UTCDateTime


class AnalysisOperationProof(Base):
    __tablename__='analysis_operation_proofs'
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey('analyses.id',ondelete='CASCADE'),primary_key=True)
    job_id: Mapped[UUID] = mapped_column(unique=True)
    # Preserve actual domain timestamps, including historical clock jumps.
    job_created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime)
    mode: Mapped[str | None] = mapped_column(String(10))
    __table_args__=(
        CheckConstraint("mode IS NULL OR mode IN ('account','guest')",name='mode'),
        Index('ix_analysis_operation_proofs_retention','finished_at','analysis_id'),
    )
