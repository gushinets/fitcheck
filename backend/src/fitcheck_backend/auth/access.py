from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .errors import AuthError
from .service import auth_transaction, active_session
from ..storage.database import unit_of_work
from ..storage.auth_repository import AuthRepository
from ..storage.models import Owner, User, Guest, Profile, Job, AnalysisRecord, AnalysisAnnotation, ImportEntry
from ..storage.ownership import delete_owner
from ..metrics.lifecycle import erase_account_metrics, append_account_deleted

RESOURCE_KEYS = {Profile: Profile.owner_id, Job: Job.id, AnalysisRecord: AnalysisRecord.id,
                 AnalysisAnnotation: AnalysisAnnotation.analysis_id, ImportEntry: ImportEntry.id}


def require_verified(principal):
    if not principal.email_verified:
        raise AuthError('email_not_verified')
    return principal


def load_owned(session, model, resource_id, principal):
    require_verified(principal)
    key = RESOURCE_KEYS.get(model)
    if key is None:
        raise AuthError('not_found')
    value = session.scalar(select(model).where(key == resource_id, model.owner_id == principal.owner_id))
    if value is None:
        raise AuthError('not_found')
    return value


class _OwnershipGraphChanged(Exception):
    pass


class AccountDeletionService:
    def __init__(self, engine, passwords, limiter, clock, *, metrics_environment=None):
        self.engine, self.passwords, self.limiter, self.clock = engine, passwords, limiter, clock
        self.metrics_environment = metrics_environment

    def delete(self, principal, password):
        self.limiter.enforce('delete', {'user': str(principal.user_id)})
        with auth_transaction(self.engine) as repo:
            user = repo.session.get(User, principal.user_id)
            if user is None or user.owner_id != principal.owner_id:
                raise AuthError('unauthenticated')
            encoded = user.password_hash
        if not self.passwords.verify(encoded, password):
            raise AuthError('invalid_credentials')
        for _ in range(3):
            try:
                with unit_of_work(self.engine) as session:
                    repo = AuthRepository(session)
                    guest_ids = set(session.scalars(select(Guest.owner_id).where(Guest.claimed_by_user_id == principal.user_id)))
                    session.scalars(select(Owner).where(Owner.id.in_({principal.owner_id, *guest_ids})).order_by(Owner.id).with_for_update()).all()
                    user = session.scalar(select(User).where(User.id == principal.user_id).with_for_update().execution_options(populate_existing=True))
                    if user is None or user.owner_id != principal.owner_id:
                        raise AuthError('unauthenticated')
                    active_session(repo, principal, self.clock())
                    if user.password_hash != encoded:
                        raise AuthError('invalid_credentials')
                    current = set(session.scalars(select(Guest.owner_id).where(Guest.claimed_by_user_id == principal.user_id)))
                    if current != guest_ids:
                        raise _OwnershipGraphChanged()
                    erase_account_metrics(session, principal.owner_id)
                    delete_owner(session, principal.owner_id)
                    append_account_deleted(session, environment=self.metrics_environment, occurred_at=self.clock())
                return
            except _OwnershipGraphChanged:
                continue
            except IntegrityError as exc:
                if exc.orig.sqlstate == '23503' and exc.orig.diag.constraint_name == 'fk_guests_claimed_by_user_id_users':
                    continue
                raise AuthError('service_unavailable') from None
            except SQLAlchemyError:
                raise AuthError('service_unavailable') from None
        raise AuthError('ownership_conflict')
