from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedMixin, IdentityMixin, UTCDateTime, utcnow


class Owner(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "owners"
    kind: Mapped[str] = mapped_column(String(10))
    __table_args__ = (UniqueConstraint("id", "kind"), CheckConstraint("kind IN ('user','guest')", name="kind"))


class User(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "users"
    owner_id: Mapped[UUID] = mapped_column(unique=True)
    owner_kind: Mapped[str] = mapped_column(String(10), default="user")
    normalized_email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(1024))
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "owner_kind"], ["owners.id", "owners.kind"], ondelete="CASCADE"),
        CheckConstraint("owner_kind = 'user'", name="kind"),
        CheckConstraint("normalized_email = lower(btrim(normalized_email)) AND length(normalized_email) > 0", name="normalized_email"),
    )


class Guest(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "guests"
    owner_id: Mapped[UUID] = mapped_column(unique=True)
    owner_kind: Mapped[str] = mapped_column(String(10), default="guest")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    claimed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "owner_kind"], ["owners.id", "owners.kind"], ondelete="CASCADE"),
        CheckConstraint("owner_kind = 'guest'", name="kind"),
        CheckConstraint("(claimed_by_user_id IS NULL) = (claimed_at IS NULL)", name="claim_pair"),
        Index("ix_guests_expiry", "expires_at"),
    )


class AuthSession(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_digest: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (UniqueConstraint('id', 'user_id'), CheckConstraint("kind IN ('web','extension')", name="kind"),
                      CheckConstraint("(kind='web' AND csrf_digest IS NOT NULL) OR (kind='extension' AND csrf_digest IS NULL)", name="csrf_kind"),
                      Index("ix_auth_sessions_expiry", "expires_at"))


class AuthToken(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "auth_tokens"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(30))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    code_challenge: Mapped[str | None] = mapped_column(String(43))
    redirect_uri: Mapped[str | None] = mapped_column(String(2048))
    issued_session_id: Mapped[UUID | None] = mapped_column()
    __table_args__ = (CheckConstraint("purpose IN ('verify_email','reset_password','extension_code')", name="purpose"),
                      ForeignKeyConstraint(['issued_session_id', 'user_id'], ['auth_sessions.id', 'auth_sessions.user_id'], ondelete='CASCADE'),
                      CheckConstraint("(purpose='extension_code' AND (issued_session_id IS NOT NULL OR consumed_at IS NOT NULL)) OR (purpose!='extension_code' AND issued_session_id IS NULL)", name='session_binding'),
                      CheckConstraint("(purpose='extension_code' AND code_challenge IS NOT NULL AND redirect_uri IS NOT NULL) OR (purpose!='extension_code' AND code_challenge IS NULL AND redirect_uri IS NULL)", name="pkce_pair"),
                      Index("ix_auth_tokens_expiry", "expires_at"))
