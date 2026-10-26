from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import CheckConstraint,ForeignKey,Integer,Numeric,String,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from .base import Base,IdentityMixin,CreatedMixin,UTCDateTime


class BudgetWindow(IdentityMixin,Base):
    __tablename__='budget_windows'
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey('owners.id',ondelete='CASCADE'))
    scope: Mapped[str] = mapped_column(String(20))
    scope_key: Mapped[str] = mapped_column(String(120))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    limit_calls: Mapped[int] = mapped_column(Integer)
    limit_tokens: Mapped[int] = mapped_column(Integer)
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(24,12))
    calls: Mapped[int] = mapped_column(Integer,default=0)
    exposure_tokens: Mapped[int] = mapped_column(Integer,default=0)
    exposure_usd: Mapped[Decimal] = mapped_column(Numeric(24,12),default=Decimal('0'))
    __table_args__=(UniqueConstraint('scope','scope_key','window_start'),
        CheckConstraint("scope IN ('deployment','owner','job')",name='scope'),
        CheckConstraint("(scope='deployment')=(owner_id IS NULL)",name='ownership'),
        CheckConstraint('limit_calls>0 AND limit_tokens>0 AND limit_usd>0',name='limits'),
        CheckConstraint('calls BETWEEN 0 AND limit_calls AND exposure_tokens BETWEEN 0 AND limit_tokens AND exposure_usd BETWEEN 0 AND limit_usd',name='capacity'))


class CallReservation(CreatedMixin,Base):
    __tablename__='call_reservations'
    provider_call_id: Mapped[UUID] = mapped_column(ForeignKey('provider_calls.id',ondelete='CASCADE'),primary_key=True)
    window_id: Mapped[UUID] = mapped_column(ForeignKey('budget_windows.id',ondelete='CASCADE'),primary_key=True)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    usd: Mapped[Decimal] = mapped_column(Numeric(24,12))
    rate_version: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20),default='reserved')
    __table_args__=(CheckConstraint('input_tokens>=0 AND output_tokens>=0 AND usd>=0',name='bounds'),
        CheckConstraint("status IN ('reserved','settled','unknown')",name='state'))
