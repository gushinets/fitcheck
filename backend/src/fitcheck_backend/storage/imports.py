from uuid import UUID
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped,mapped_column
from .base import Base,OwnedMixin


class ImportItem(OwnedMixin,Base):
    __tablename__='import_items'
    job_id: Mapped[UUID]=mapped_column(primary_key=True)
    item_index: Mapped[int]=mapped_column(Integer,primary_key=True)
    outcome: Mapped[dict]=mapped_column(JSONB)
    __table_args__=(
        ForeignKeyConstraint(['job_id','owner_id'],['jobs.id','jobs.owner_id'],ondelete='CASCADE'),
        CheckConstraint('item_index BETWEEN -2 AND 999',name='index'),
        CheckConstraint("jsonb_typeof(outcome)='object'",name='outcome'),
    )
