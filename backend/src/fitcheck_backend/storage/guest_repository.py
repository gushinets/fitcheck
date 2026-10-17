from sqlalchemy import select
from ..auth.errors import AuthError
from .models import Guest, GuestSessionRow, AuthSession, User


def require_identity(session, identity, now, *, allow_claim_receipt=False):
    if identity.mode=='account':
        user=session.scalar(select(User).where(User.id==identity.user_id,User.owner_id==identity.owner_id))
        row=session.scalar(select(AuthSession).where(AuthSession.id==identity.session_id,AuthSession.user_id==identity.user_id).with_for_update())
        if not user or not row or row.revoked_at is not None or row.expires_at<=now:
            raise AuthError('unauthenticated')
        if user.email_verified_at is None: raise AuthError('email_not_verified')
        return user
    guest=session.scalar(select(Guest).where(Guest.owner_id==identity.owner_id))
    row=session.scalar(select(GuestSessionRow).where(GuestSessionRow.id==identity.session_id,GuestSessionRow.owner_id==identity.owner_id).with_for_update())
    if (not guest or not row or row.revoked_at is not None or row.expires_at<=now or guest.expires_at<=now
            or (guest.claimed_at is not None and not allow_claim_receipt)):
        raise AuthError('unauthenticated')
    return guest
