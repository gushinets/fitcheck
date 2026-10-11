from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedMixin, IdentityMixin, OwnedMixin, UTCDateTime, utcnow


class VacancyRecord(OwnedMixin, CreatedMixin, IdentityMixin, Base):
    __tablename__ = "vacancies"
    vacancy: Mapped[dict] = mapped_column(JSONB)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    __table_args__ = (UniqueConstraint("id", "owner_id"), CheckConstraint("jsonb_typeof(vacancy) = 'object'", name="vacancy_object"))


class Job(OwnedMixin, CreatedMixin, IdentityMixin, Base):
    __tablename__ = "jobs"
    type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    input: Mapped[dict] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    lease_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    __table_args__ = (
        UniqueConstraint("owner_id", "type", "idempotency_key"), UniqueConstraint("id", "owner_id"), UniqueConstraint("id", "owner_id", "type"),
        CheckConstraint("type IN ('analysis','skill_suggestions','import')", name="type"),
        CheckConstraint("status IN ('queued','running','succeeded','failed')", name="status"),
        CheckConstraint("jsonb_typeof(input) = 'object'", name="input_object"),
        CheckConstraint("length(idempotency_key) BETWEEN 1 AND 200 AND request_hash ~ '^[0-9a-f]{64}$'", name="idempotency"),
        CheckConstraint("attempts >= 0", name="attempts"),
        CheckConstraint("(status='running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status!='running' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="lease"),
        CheckConstraint("(status IN ('succeeded','failed')) = (finished_at IS NOT NULL)", name="finished"),
        CheckConstraint("(status='failed' AND error IS NOT NULL AND jsonb_typeof(error)='object') OR (status!='failed' AND error IS NULL)", name="error"),
        CheckConstraint("(status='succeeded' AND type IN ('skill_suggestions','import') AND output IS NOT NULL AND jsonb_typeof(output)='object') OR (NOT(status='succeeded' AND type IN ('skill_suggestions','import')) AND output IS NULL)", name="output"),
        CheckConstraint("status!='succeeded' OR type!='skill_suggestions' OR (output ? 'skills' AND jsonb_typeof(output->'skills')='array')", name="suggestion_output"),
        CheckConstraint("status!='succeeded' OR type!='import' OR (output ? 'importedCount' AND jsonb_typeof(output->'importedCount')='number')", name="import_output"),
        Index("ix_jobs_schedule", "status", "available_at"), Index("ix_jobs_lease", "status", "lease_expires_at"),
    )


class AnalysisRecord(OwnedMixin, CreatedMixin, IdentityMixin, Base):
    __tablename__ = "analyses"
    job_id: Mapped[UUID | None] = mapped_column(unique=True)
    job_type: Mapped[str | None] = mapped_column(String(30))
    vacancy_id: Mapped[UUID]
    profile_revision: Mapped[int | None] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    analysis: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(["job_id", "owner_id", "job_type"], ["jobs.id", "jobs.owner_id", "jobs.type"], deferrable=True, initially="IMMEDIATE"),
        ForeignKeyConstraint(["vacancy_id", "owner_id"], ["vacancies.id", "vacancies.owner_id"], deferrable=True, initially="IMMEDIATE"),
        ForeignKeyConstraint(["owner_id", "profile_revision"], ["profile_revisions.owner_id", "profile_revisions.revision"], deferrable=True, initially="IMMEDIATE"),
        CheckConstraint("(job_id IS NULL AND job_type IS NULL) OR (job_id IS NOT NULL AND job_type IS NOT NULL AND job_type='analysis')", name="job_pair"),
        CheckConstraint("jsonb_typeof(snapshot)='object' AND jsonb_typeof(analysis)='object'", name="payload_objects"),
    )


Index("ix_analyses_history", AnalysisRecord.owner_id, AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc())


class AnalysisAnnotation(OwnedMixin, Base):
    __tablename__ = "analysis_annotations"
    analysis_id: Mapped[UUID] = mapped_column(primary_key=True)
    corrected_score: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(500))
    feedback_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    application_status: Mapped[str] = mapped_column(String(20), default="not_applied")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["analysis_id", "owner_id"], ["analyses.id", "analyses.owner_id"], deferrable=True, initially="IMMEDIATE", ondelete="CASCADE"),
        CheckConstraint("corrected_score BETWEEN 0 AND 100", name="score"),
        CheckConstraint("(corrected_score IS NULL AND note IS NULL AND feedback_created_at IS NULL) OR (corrected_score IS NOT NULL AND feedback_created_at IS NOT NULL)", name="feedback"),
        CheckConstraint("application_status IN ('not_applied','applied','replied','interview','rejected','hired')", name="status"),
        Index("ix_annotations_status", "owner_id", "application_status"),
    )


class ImportEntry(OwnedMixin, CreatedMixin, IdentityMixin, Base):
    __tablename__ = "import_entries"
    source: Mapped[str] = mapped_column(String(20), default="local_v1")
    external_id: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64))
    analysis_id: Mapped[UUID]
    __table_args__ = (
        UniqueConstraint("owner_id", "source", "external_id"),
        ForeignKeyConstraint(["analysis_id", "owner_id"], ["analyses.id", "analyses.owner_id"], deferrable=True, initially="IMMEDIATE", ondelete="CASCADE"),
        CheckConstraint("source='local_v1' AND content_hash ~ '^[0-9a-f]{64}$'", name="source_hash"),
    )
