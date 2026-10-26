from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedMixin, IdentityMixin, OwnedMixin, UTCDateTime, utcnow


class Profile(OwnedMixin, Base):
    __tablename__ = "profiles"
    # One profile per owner; revisions belong directly to the owner.
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True)
    current_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("current_revision >= 1", name="revision"),
                      ForeignKeyConstraint(["owner_id", "current_revision"], ["profile_revisions.owner_id", "profile_revisions.revision"], deferrable=True, initially="DEFERRED"))


class ProfileRevision(OwnedMixin, CreatedMixin, IdentityMixin, Base):
    __tablename__ = "profile_revisions"
    revision: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("owner_id", "revision"), CheckConstraint("revision >= 1", name="revision"),
                      CheckConstraint("jsonb_typeof(profile) = 'object'", name="profile_object"))


class Preference(OwnedMixin, Base):
    __tablename__ = "preferences"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True)
    locale: Mapped[str] = mapped_column(String(2))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (CheckConstraint("locale IN ('ru','en')", name="locale"),)


class Draft(OwnedMixin, Base):
    __tablename__ = "drafts"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True)
    vacancy: Mapped[dict] = mapped_column(JSONB)
    locale: Mapped[str] = mapped_column(String(2))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (CheckConstraint("locale IN ('ru','en')", name="locale"), CheckConstraint("jsonb_typeof(vacancy) = 'object'", name="vacancy_object"))
