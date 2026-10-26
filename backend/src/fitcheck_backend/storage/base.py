from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware UTC datetime required")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        return None if value is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class IdentityMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class OwnedMixin:
    owner_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=lambda: utcnow(), nullable=False)


def utcnow() -> datetime:
    return datetime.now(UTC)
