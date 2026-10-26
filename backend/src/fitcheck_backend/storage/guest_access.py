from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, OwnedMixin, IdentityMixin, CreatedMixin, UTCDateTime


class GuestSessionRow(OwnedMixin,IdentityMixin,CreatedMixin,Base):
    __tablename__='guest_sessions'
    token_digest: Mapped[str] = mapped_column(String(64),unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__=(CheckConstraint("token_digest ~ '^[0-9a-f]{64}$'",name='digest'),)


class GuestClaimReceipt(IdentityMixin,CreatedMixin,Base):
    __tablename__='guest_claim_receipts'
    account_owner_id: Mapped[UUID] = mapped_column(ForeignKey('owners.id',ondelete='CASCADE'))
    guest_owner_id: Mapped[UUID] = mapped_column(ForeignKey('owners.id',ondelete='CASCADE'))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    claimed_count: Mapped[int] = mapped_column(Integer)
    profile_imported: Mapped[bool] = mapped_column(Boolean)
    __table_args__=(UniqueConstraint('account_owner_id','idempotency_key'),
        CheckConstraint('claimed_count>=0',name='count'),
        CheckConstraint("length(idempotency_key) BETWEEN 1 AND 200 AND request_hash ~ '^[0-9a-f]{64}$'",name='key_hash'))
