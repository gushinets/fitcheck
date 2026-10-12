from contextlib import contextmanager
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .crypto import TOKEN_PATTERN
from .errors import AuthError
from .types import Principal, IssuedSession, MailMessage
from .mail import MailDeliveryError
from ..contracts.resources import normalize_email
from ..storage.database import unit_of_work
from ..storage.auth_repository import AuthRepository
from ..storage.identity import User, Owner, AuthSession


@contextmanager
def auth_transaction(engine):
    try:
        with unit_of_work(engine) as session:
            yield AuthRepository(session)
    except SQLAlchemyError:
        raise AuthError('service_unavailable') from None


def principal_for(user, session) -> Principal:
    if user is None:
        raise AuthError('unauthenticated')
    return Principal(user.id, user.owner_id, session.id, session.kind, user.normalized_email, user.email_verified_at is not None)


def active_session(repo, principal, now):
    value = repo.session.scalar(select(AuthSession).where(AuthSession.id == principal.session_id,
        AuthSession.user_id == principal.user_id, AuthSession.kind == principal.kind,
        AuthSession.revoked_at.is_(None), AuthSession.expires_at > now).with_for_update().execution_options(populate_existing=True))
    if value is None:
        raise AuthError('unauthenticated')
    return value


class AuthService:
    def __init__(self, engine, crypto, passwords, limiter, mailer, clock):
        self.engine, self.crypto, self.passwords = engine, crypto, passwords
        self.limiter, self.mailer, self.clock = limiter, mailer, clock

    def _issue(self, repo, user):
        raw = self.crypto.new_token()
        csrf = self.crypto.session_csrf(raw)
        expiry = self.clock() + timedelta(days=7)
        value = repo.create_session(user, 'web', self.crypto.digest(raw), self.crypto.digest(csrf), expiry)
        return IssuedSession(principal_for(user, value), raw, csrf, expiry)

    def _lock_login_users(self, repo, user_id, old_session_token):
        old = repo.session_by_digest(self.crypto.digest(old_session_token), 'web', self.clock()) if old_session_token else None
        ids = {user_id} | ({old.user_id} if old else set())
        owner_ids = select(User.owner_id).where(User.id.in_(ids))
        repo.session.scalars(select(Owner).where(Owner.id.in_(owner_ids)).order_by(Owner.id).with_for_update(read=True, key_share=True)).all()
        users = repo.session.scalars(select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update().execution_options(populate_existing=True)).all()
        return next((u for u in users if u.id == user_id), None)

    def _rotate(self, repo, old_session_token):
        if old_session_token:
            old = repo.session_by_digest(self.crypto.digest(old_session_token), 'web', self.clock())
            if old is not None:
                repo.revoke_sessions(old.user_id, self.clock(), session_id=old.id)

    def register(self, email, password, client_ip, *, old_session_token=None):
        email = normalize_email(email)
        self.limiter.enforce('register', {'ip': client_ip})
        if not self.mailer.available():
            raise AuthError('email_unavailable')
        encoded = self.passwords.hash(password)
        verification = self.crypto.new_token()
        try:
            with unit_of_work(self.engine) as session:
                repo = AuthRepository(session)
                user = repo.create_user(email, encoded)
                self._lock_login_users(repo, user.id, old_session_token)
                self._rotate(repo, old_session_token)
                repo.create_token(user, 'verify_email', self.crypto.digest(verification), self.clock() + timedelta(hours=24))
                issued = self._issue(repo, user)
        except IntegrityError as exc:
            if exc.orig.sqlstate == '23505' and exc.orig.diag.constraint_name == 'uq_users_normalized_email':
                raise AuthError('registration_conflict') from None
            raise AuthError('service_unavailable') from None
        except SQLAlchemyError:
            raise AuthError('service_unavailable') from None
        try:
            self.mailer.send(MailMessage(email, 'verify_email', verification))
        except MailDeliveryError:
            raise AuthError('email_unavailable') from None
        return issued

    def login(self, email, password, client_ip, *, old_session_token=None):
        email = normalize_email(email)
        self.limiter.enforce('login', {'email': email, 'ip': client_ip})
        with auth_transaction(self.engine) as repo:
            user = repo.find_user(email)
            user_id = user.id if user else None
            encoded = user.password_hash if user else self.passwords.dummy_hash
        verified = self.passwords.verify(encoded, password)
        if user_id is None or not verified:
            raise AuthError('invalid_credentials')
        replacement = self.passwords.hash(password) if self.passwords.needs_rehash(encoded) else None
        with auth_transaction(self.engine) as repo:
            user = self._lock_login_users(repo, user_id, old_session_token)
            if user is None or user.password_hash != encoded:
                raise AuthError('invalid_credentials')
            if replacement:
                user.password_hash = replacement
                user.updated_at = self.clock()
            self._rotate(repo, old_session_token)
            return self._issue(repo, user)

    def session(self, token):
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise AuthError('unauthenticated')
        with auth_transaction(self.engine) as repo:
            value = repo.session_by_digest(self.crypto.digest(token), 'web', self.clock())
            if value is None:
                raise AuthError('unauthenticated')
            user = repo.session.get(User, value.user_id)
            csrf = self.crypto.session_csrf(token)
            import hmac
            if not hmac.compare_digest(self.crypto.digest(csrf), value.csrf_digest):
                raise AuthError('unauthenticated')
            return IssuedSession(principal_for(user, value), token, csrf, value.expires_at)

    def resolve(self, token, kind):
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise AuthError('unauthenticated')
        with auth_transaction(self.engine) as repo:
            value = repo.session_by_digest(self.crypto.digest(token), kind, self.clock())
            if value is None:
                raise AuthError('unauthenticated')
            user = repo.session.get(User, value.user_id)
            return principal_for(user, value)

    def logout(self, principal):
        with auth_transaction(self.engine) as repo:
            user = repo.lock_user(principal.user_id)
            if user is None or user.owner_id != principal.owner_id or principal.kind != 'web':
                raise AuthError('unauthenticated')
            active_session(repo, principal, self.clock())
            repo.revoke_sessions(user.id, self.clock(), session_id=principal.session_id)
