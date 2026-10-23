"""Optional analytics around successful business operations; no raw identity logs."""
import logging
from sqlalchemy import select, update, text, func
from sqlalchemy.dialects.postgresql import insert
from ..auth.errors import AuthError
from ..auth.service import active_session
from ..storage.auth_repository import AuthRepository
from ..storage.database import unit_of_work
from ..storage.guest_repository import require_identity
from ..storage.models import Owner, User, AuthSession, GuestClaimReceipt
from ..storage.metric_identity import MetricIdentityTransition as Link, MetricVisitorBoundary as Boundary
from .repository import MetricRepository, fingerprint
from .identity_proof import verify_visitor_proof

logger=logging.getLogger(__name__)


def visitor_context(request):
    runtime=request.app.state.auth_runtime
    values=request.headers.getlist('x-fitcheck-visitor-proof')
    if runtime is None or len(values)!=1:
        return None
    return verify_visitor_proof(values[0],runtime.settings,method=request.method,path=request.url.path,now=runtime.clock())


def lock_visitor(session,environment,visitor):
    key=int(fingerprint({'environment':environment,'visitor':str(visitor)})[:16],16)
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':key-(1<<64) if key>=(1<<63) else key})


def boundary(session,environment,visitor,at):
    statement=insert(Boundary).values(environment=environment,visitor_id=visitor,anonymous_floor=at)
    session.execute(statement.on_conflict_do_update(index_elements=['environment','visitor_id'],
        set_={'anonymous_floor':func.greatest(Boundary.anonymous_floor,at)}))


def advance_boundary(session,environment,visitor,at):
    # Only recording a new attested operation may create a visitor association.
    session.execute(update(Boundary).where(Boundary.environment==environment,Boundary.visitor_id==visitor)
        .values(anonymous_floor=func.greatest(Boundary.anonymous_floor,at)))


def archive_sessions(session,ids,now):
    """Failure leaves the source sessions authoritative and prevents their pruning."""
    try:
        with session.begin_nested():
            rows=session.execute(select(Link,AuthSession).join(AuthSession,AuthSession.id==Link.auth_session_id)
                .where(AuthSession.id.in_(ids),Link.kind!='claim')
                .order_by(Link.environment,Link.visitor_id,Link.id)).all()
            for link,auth in rows:
                if auth.revoked_at is None and auth.expires_at>now:
                    continue
                link.ended_at=min(auth.expires_at,auth.revoked_at or auth.expires_at)
                link.end_basis='revoked' if auth.revoked_at and auth.revoked_at<auth.expires_at else 'expired'
                session.flush()  # Match erasure's link-before-boundary lock order.
                advance_boundary(session,link.environment,link.visitor_id,link.ended_at)
            session.flush()
        return True
    except Exception:
        logger.warning('metrics_identity_unavailable operation=session_archive')
        return False


def account_boundary(session,owner_ids,now):
    rows=session.execute(select(Link.environment,Link.visitor_id).where(Link.account_owner_id.in_(owner_ids))
        .distinct().order_by(Link.environment,Link.visitor_id)).all()
    # Preserve only anonymous temporal guards. Removing a switch target must
    # never reopen an older account, including overlapping auth requests.
    # UPDATE only: a concurrent visitor erasure cannot be resurrected from the
    # stale visitor list above. Match visitor deletion's link-before-floor order;
    # never acquire a visitor advisory lock after the domain's owner lock.
    session.execute(update(Link).where(Link.account_owner_id.in_(owner_ids),Link.kind!='claim')
        .values(kind='erased',account_owner_id=None,source_id=None,auth_session_id=None,
                anonymous_from=None,ended_at=None,end_basis=None))
    for environment,visitor in rows:
        advance_boundary(session,environment,visitor,now)


class IdentityRecorder:
    def __init__(self,engine,settings,clock):
        self.engine,self.settings,self.clock=engine,settings,clock

    def auth(self,context,issued,kind):
        if context is None or not self.settings.metrics_configured:
            return
        try:
            self._write_auth(context,issued,kind)
        except Exception:
            logger.warning('metrics_identity_unavailable operation=auth')

    def _prepare(self,session,context,principal):
        environment=self.settings.metrics_environment
        lock_visitor(session,environment,context.visitor_id)
        if MetricRepository(session).visitor_erased(context.visitor_id,environment):
            return None
        owner=session.scalar(select(Owner).where(Owner.id==principal.owner_id).with_for_update(read=True,key_share=True))
        user=session.get(User,principal.user_id)
        if owner is None or owner.kind!='user' or user is None or user.owner_id!=principal.owner_id:
            return None
        auth=active_session(AuthRepository(session),principal,self.clock())
        return user,auth

    def _write_auth(self,context,issued,kind):
        if kind not in {'registered','login'}:
            return
        with unit_of_work(self.engine) as s:
            prepared=self._prepare(s,context,issued.principal)
            if prepared is None:return
            user,auth=prepared
            environment=self.settings.metrics_environment
            if s.scalar(select(Link.id).where(Link.environment==environment,Link.kind==kind,Link.source_id==auth.id)):
                return
            at=max(self.clock(),user.created_at,auth.created_at)
            if context.cookie_issued_at>at or auth.expires_at<=at:return
            floor=s.get(Boundary,(environment,context.visitor_id))
            anonymous_from=max(context.cookie_issued_at,floor.anonymous_floor if floor else context.cookie_issued_at)
            previous=s.execute(select(Link,AuthSession).outerjoin(AuthSession,AuthSession.id==Link.auth_session_id)
                .where(Link.environment==environment,Link.visitor_id==context.visitor_id,Link.kind!='claim')).all()
            for old,source in previous:
                end=(min(source.expires_at,source.revoked_at or source.expires_at) if source else old.ended_at)
                anonymous_from=max(anonymous_from,min(at,end) if end is not None else at)
            inserted=s.scalar(insert(Link).values(environment=environment,visitor_id=context.visitor_id,
                account_owner_id=user.owner_id,guest_owner_id=None,kind=kind,source_id=auth.id,auth_session_id=auth.id,
                cookie_issued_at=context.cookie_issued_at,request_started_at=min(context.received_at,at),occurred_at=at,
                anonymous_from=min(anonymous_from,at) if kind=='registered' else None,expires_at=auth.expires_at,
                ended_at=None,end_basis=None).on_conflict_do_nothing().returning(Link.id))
            if inserted:boundary(s,environment,context.visitor_id,at)

    def claim(self,context,account,guest,key):
        if context is None or not self.settings.metrics_configured:
            return
        try:
            self._write_claim(context,account,guest,key)
        except Exception:
            logger.warning('metrics_identity_unavailable operation=claim')

    def _write_claim(self,context,account,guest,key):
        with unit_of_work(self.engine) as s:
            # Match the domain claim's owner order before touching session rows.
            lock_visitor(s,self.settings.metrics_environment,context.visitor_id)
            s.scalars(select(Owner).where(Owner.id.in_([account.owner_id,guest.owner_id]))
                .order_by(Owner.id).with_for_update(read=True,key_share=True)).all()
            prepared=self._prepare(s,context,account)
            if prepared is None or prepared[0].email_verified_at is None:return
            original=require_identity(s,guest,self.clock(),allow_claim_receipt=True)
            receipt=s.scalar(select(GuestClaimReceipt).where(GuestClaimReceipt.account_owner_id==account.owner_id,
                GuestClaimReceipt.guest_owner_id==guest.owner_id,GuestClaimReceipt.idempotency_key==key))
            if (receipt is None or original.claimed_by_user_id!=account.user_id
                    or context.cookie_issued_at>receipt.created_at):return
            s.execute(insert(Link).values(environment=self.settings.metrics_environment,visitor_id=context.visitor_id,
                account_owner_id=account.owner_id,guest_owner_id=guest.owner_id,kind='claim',source_id=receipt.id,
                auth_session_id=account.session_id,cookie_issued_at=context.cookie_issued_at,
                request_started_at=min(context.received_at,receipt.created_at),occurred_at=receipt.created_at,
                anonymous_from=None,expires_at=None,ended_at=None,end_basis=None).on_conflict_do_nothing())
