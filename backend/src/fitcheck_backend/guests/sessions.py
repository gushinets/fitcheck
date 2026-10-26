from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from .types import AccessIdentity,IssuedGuestSession
from ..auth.crypto import TOKEN_PATTERN
from ..auth.errors import AuthError
from ..storage.job_queue import job_transaction
from ..storage.models import Owner, Guest, GuestSessionRow
from ..storage.guest_repository import require_identity


def guest_cookie_name(settings):
    return ('__Host-' if settings.env=='production' else '')+'fitcheck_guest'


class GuestSessions:
    def __init__(self,engine,crypto,policy,clock,limiter):
        self.engine,self.crypto,self.policy,self.clock,self.limiter=engine,crypto,policy,clock,limiter

    def csrf(self,token):
        return self.crypto._mac('guest-session-csrf',token)

    require_active=staticmethod(require_identity)

    def resolve(self,raw_cookie,*,allow_claim_receipt=False):
        if not isinstance(raw_cookie,str) or TOKEN_PATTERN.fullmatch(raw_cookie) is None:
            raise AuthError('unauthenticated')
        try:
            with job_transaction(self.engine) as s:
                row=s.scalar(select(GuestSessionRow).where(GuestSessionRow.token_digest==self.crypto.digest(raw_cookie)))
                if row is None: raise AuthError('unauthenticated')
                identity=AccessIdentity('guest',row.owner_id,row.id,row.expires_at)
                require_identity(s,identity,self.clock(),allow_claim_receipt=allow_claim_receipt)
                return identity
        except SQLAlchemyError:
            raise AuthError('service_unavailable') from None

    def issue_or_reuse(self,raw_cookie,*,client_ip):
        if raw_cookie:
            try:
                identity=self.resolve(raw_cookie)
                return IssuedGuestSession(raw_cookie,self.csrf(raw_cookie),identity)
            except AuthError as exc:
                if exc.code!='unauthenticated': raise
        self.limiter.enforce('guest_create',{'ip_hour':client_ip,'ip_day':client_ip},rules=[
            ('ip_hour',self.policy.create_hourly,3600),('ip_day',self.policy.create_daily,86400)])
        token=self.crypto.new_token()
        now=self.clock();expiry=now+timedelta(seconds=self.policy.guest_ttl_seconds)
        try:
            with job_transaction(self.engine) as s:
                owner=Owner(kind='guest',created_at=now);s.add(owner);s.flush()
                s.add(Guest(owner_id=owner.id,expires_at=expiry,created_at=now))
                row=GuestSessionRow(owner_id=owner.id,token_digest=self.crypto.digest(token),expires_at=expiry)
                s.add(row);s.flush()
                return IssuedGuestSession(token,self.csrf(token),AccessIdentity('guest',owner.id,row.id,expiry))
        except SQLAlchemyError:
            raise AuthError('service_unavailable') from None
