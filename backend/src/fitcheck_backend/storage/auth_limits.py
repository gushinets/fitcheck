from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, UTCDateTime


class AuthRateBucket(Base):
    __tablename__ = 'auth_rate_buckets'
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    attempts: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    __table_args__ = (CheckConstraint('attempts > 0', name='positive_attempts'),
                      CheckConstraint('expires_at > window_start', name='expiry'),
                      Index('ix_auth_rate_buckets_expiry', 'expires_at'))
