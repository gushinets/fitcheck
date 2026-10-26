from datetime import UTC,timedelta
from sqlalchemy import select,update
from sqlalchemy.dialects.postgresql import insert
from ..quotas.errors import QuotaError
from ..auth.errors import AuthError
from .models import Owner,Guest,Job,QuotaBucket,QuotaReservation,ExtractionReservation


def quota_window(owner,guest,now):
    if owner.kind=='guest': return guest.created_at,guest.expires_at
    start=now.astimezone(UTC).replace(hour=0,minute=0,second=0,microsecond=0)
    return start,start+timedelta(days=1)


class QuotaRepository:
    def __init__(self,session): self.s=session

    def bucket(self,owner_id,operation,policy,now):
        owner=self.s.scalar(select(Owner).where(Owner.id==owner_id).with_for_update())
        if owner is None: raise AuthError('unauthenticated')
        guest=self.s.scalar(select(Guest).where(Guest.owner_id==owner_id)) if owner.kind=='guest' else None
        if owner.kind=='guest' and guest is None: raise AuthError('unauthenticated')
        start,end=quota_window(owner,guest,now)
        # Session's immutable expiry anchors its entire quota lifetime, irrespective of later policy changes.
        if guest is not None:start=guest.created_at
        mode='guest' if guest is not None else 'account'
        limit=getattr(policy.limits(mode),operation)
        key='v1:'+operation+':'+mode
        self.s.execute(insert(QuotaBucket).values(owner_id=owner_id,policy_key=key,window_start=start,
            resets_at=end,limit=limit,reserved=0,consumed=0).on_conflict_do_nothing(index_elements=['owner_id','policy_key','window_start']))
        return self.s.scalar(select(QuotaBucket).where(QuotaBucket.owner_id==owner_id,
            QuotaBucket.policy_key==key,QuotaBucket.window_start==start).with_for_update().execution_options(populate_existing=True))

    def _reserve(self,bucket,now):
        if bucket.reserved+bucket.consumed>=bucket.limit:
            raise QuotaError('quota_exceeded',retry_after=max(1,int((bucket.resets_at-now).total_seconds())) if bucket.resets_at else None)
        bucket.reserved+=1;self.s.flush()

    def reserve_job(self,owner_id,job_id,operation,policy,now):
        bucket=self.bucket(owner_id,operation,policy,now)
        job=self.s.scalar(select(Job).where(Job.id==job_id,Job.owner_id==owner_id))
        if job is None:raise AuthError('not_found')
        existing=self.s.scalar(select(QuotaReservation).where(QuotaReservation.job_id==job_id,QuotaReservation.bucket_id==bucket.id))
        if existing:return existing
        self._reserve(bucket,now)
        row=QuotaReservation(owner_id=owner_id,job_id=job_id,bucket_id=bucket.id,units=1,status='reserved')
        self.s.add(row);self.s.flush();return row

    def _settle(self,model,key,success,now):
        candidate=self.s.get(model,key)
        if candidate is None:return False
        # Every lifecycle caller locks owner/job first; bucket precedes reservation.
        bucket=self.s.scalar(select(QuotaBucket).where(QuotaBucket.id==candidate.bucket_id).with_for_update().execution_options(populate_existing=True))
        row=self.s.scalar(select(model).where(model.id==key).with_for_update().execution_options(populate_existing=True))
        if row is None or row.status!='reserved':return False
        row.status='consumed' if success else 'released';row.updated_at=now
        bucket.reserved-=1
        if success:bucket.consumed+=1
        self.s.flush();return True

    def settle_job(self,job_id,*,success,now):
        rows=self.s.scalars(select(QuotaReservation).where(QuotaReservation.job_id==job_id).order_by(QuotaReservation.bucket_id)).all()
        changed=False
        for row in rows:changed=self._settle(QuotaReservation,row.id,success,now) or changed
        return changed

    def reserve_extraction(self,owner_id,operation_id,policy,now):
        bucket=self.bucket(owner_id,'extraction',policy,now)
        self._reserve(bucket,now)
        row=ExtractionReservation(id=operation_id,owner_id=owner_id,bucket_id=bucket.id,expires_at=now+timedelta(seconds=120))
        self.s.add(row);self.s.flush();return row

    def settle_extraction(self,operation_id,*,success,now):
        row=self.s.get(ExtractionReservation,operation_id)
        if row is None:return False
        if row.expires_at<=now:
            self._settle(ExtractionReservation,operation_id,False,now);return False
        return self._settle(ExtractionReservation,operation_id,success,now)

    def reap_extractions(self,now,*,limit=100,owner_id=None):
        query=select(ExtractionReservation).where(ExtractionReservation.status=='reserved',ExtractionReservation.expires_at<=now)
        if owner_id is not None:query=query.where(ExtractionReservation.owner_id==owner_id)
        rows=self.s.scalars(query.order_by(ExtractionReservation.owner_id,ExtractionReservation.id).limit(limit)).all()
        count=0
        for row in rows:
            owner=self.s.scalar(select(Owner.id).where(Owner.id==row.owner_id).with_for_update(skip_locked=True))
            if owner is not None:count+=int(self._settle(ExtractionReservation,row.id,False,now))
        return count
