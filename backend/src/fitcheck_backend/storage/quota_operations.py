from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint,ForeignKeyConstraint,String
from sqlalchemy.orm import Mapped,mapped_column
from .base import Base,OwnedMixin,IdentityMixin,CreatedMixin,UTCDateTime,utcnow


class ExtractionReservation(OwnedMixin,IdentityMixin,CreatedMixin,Base):
    __tablename__='extraction_reservations'
    bucket_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(20),default='reserved')
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime,default=utcnow)
    __table_args__=(ForeignKeyConstraint(['bucket_id','owner_id'],['quota_buckets.id','quota_buckets.owner_id'],ondelete='CASCADE'),
        CheckConstraint("status IN ('reserved','consumed','released')",name='state'))
