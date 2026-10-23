from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from ..auth.access import require_verified
from ..auth.errors import AuthError
from ..auth.service import active_session
from ..storage.auth_repository import AuthRepository
from ..storage.database import unit_of_work
from ..storage.job_queue import job_transaction
from ..storage.models import Owner,User,Guest,GuestClaimReceipt,ExtractionReservation
from ..storage.guest_repository import require_identity
from ..storage.quota_repository import QuotaRepository
from ..storage.profile_repository import get_profile,create_profile
from ..storage.ownership import transfer_guest_analyses,OwnershipConflict
from ..storage.payloads import canonical_hash
from ..contracts.guests import GuestClaimResult
from ..jobs.errors import JobError


class GuestClaimService:
    def __init__(self,engine,clock):self.engine,self.clock=engine,clock

    def claim(self,*,account,guest,idempotency_key):
        require_verified(account)
        if guest.mode!='guest' or not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=200:
            raise JobError('invalid_request')
        digest=canonical_hash({'guest':str(guest.owner_id)})
        try:
            with job_transaction(self.engine) as s:
                owners=s.scalars(select(Owner).where(Owner.id.in_([account.owner_id,guest.owner_id])).order_by(Owner.id).with_for_update()).all()
                if {o.id:o.kind for o in owners}!={account.owner_id:'user',guest.owner_id:'guest'}:
                    raise AuthError('unauthenticated')
                user=s.get(User,account.user_id)
                if user is None or user.owner_id!=account.owner_id:raise AuthError('unauthenticated')
                if user.email_verified_at is None:raise AuthError('email_not_verified')
                active_session(AuthRepository(s),account,self.clock())
                live=require_identity(s,guest,self.clock(),allow_claim_receipt=True)
                receipt=s.scalar(select(GuestClaimReceipt).where(GuestClaimReceipt.account_owner_id==account.owner_id,GuestClaimReceipt.idempotency_key==idempotency_key))
                if receipt:
                    if receipt.request_hash!=digest or receipt.guest_owner_id!=guest.owner_id:raise JobError('conflict')
                    return GuestClaimResult(claimedCount=receipt.claimed_count,profileImported=receipt.profile_imported)
                if live.claimed_by_user_id is not None:raise JobError('conflict')
                QuotaRepository(s).reap_extractions(self.clock(),owner_id=guest.owner_id)
                if s.scalar(select(ExtractionReservation.id).where(ExtractionReservation.owner_id==guest.owner_id,ExtractionReservation.status=='reserved').limit(1)):
                    raise JobError('conflict')
                profile=get_profile(s,guest.owner_id)
                imported=profile is not None and get_profile(s,account.owner_id) is None
                # Transfer validates pending jobs/key collisions inside a savepoint.
                # Profile and receipt are still in the encompassing atomic transaction.
                count=transfer_guest_analyses(s,guest.owner_id,account.owner_id)
                if imported:create_profile(s,account.owner_id,profile.profile)
                s.add(GuestClaimReceipt(created_at=self.clock(),account_owner_id=account.owner_id,guest_owner_id=guest.owner_id,
                    idempotency_key=idempotency_key,request_hash=digest,claimed_count=count,profile_imported=imported))
                s.flush()
                return GuestClaimResult(claimedCount=count,profileImported=imported)
        except OwnershipConflict:raise JobError('conflict') from None
        except SQLAlchemyError:raise AuthError('service_unavailable') from None
