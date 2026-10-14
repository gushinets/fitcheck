import logging
from datetime import timedelta
from sqlalchemy import select
from .crypto import TOKEN_PATTERN
from .types import MailMessage
from .errors import AuthError
from .mail import MailDeliveryError
from .service import auth_transaction, active_session
from ..contracts.resources import normalize_email
from ..storage.identity import AuthToken
from ..metrics.lifecycle import append_domain_event, registration_key, verification_key

logger = logging.getLogger('fitcheck.auth.email')


class EmailAuthService:
    def __init__(self, engine, crypto, passwords, limiter, mailer, clock, *, metrics_environment=None):
        self.engine, self.crypto, self.passwords = engine, crypto, passwords
        self.limiter, self.mailer, self.clock = limiter, mailer, clock
        self.metrics_environment = metrics_environment

    def _request(self, email, client_ip, purpose, action):
        email = normalize_email(email)
        self.limiter.enforce(action, {'email': email, 'ip': client_ip})
        if not self.mailer.available():
            raise AuthError('email_unavailable')
        raw = self.crypto.new_token()
        with auth_transaction(self.engine) as repo:
            found = repo.find_user(email)
            user = repo.lock_user(found.id) if found else None
            if user is None or purpose == 'verify_email' and user.email_verified_at is not None:
                return
            repo.invalidate_tokens(user.id, purpose, self.clock())
            expiry = self.clock() + (timedelta(hours=24) if purpose == 'verify_email' else timedelta(minutes=30))
            repo.create_token(user, purpose, self.crypto.digest(raw), expiry)
        try:
            self.mailer.send(MailMessage(email, purpose, raw))
        except MailDeliveryError:
            logger.warning('email_delivery_failed purpose=%s', purpose)

    def request_verification(self, email, client_ip):
        self._request(email, client_ip, 'verify_email', 'verify_request')

    def request_reset(self, email, client_ip):
        self._request(email, client_ip, 'reset_password', 'reset_request')

    def _check_token(self, token, user_id):
        if token is None or token.user_id != user_id or token.consumed_at is not None or token.expires_at <= self.clock():
            raise AuthError('invalid_token')

    def verify(self, principal, token, client_ip):
        self.limiter.enforce('verify_confirm', {'ip': client_ip})
        if principal.kind != 'web':
            raise AuthError('forbidden')
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise AuthError('invalid_token')
        with auth_transaction(self.engine) as repo:
            user = repo.lock_user(principal.user_id)
            if user is None or user.owner_id != principal.owner_id:
                raise AuthError('unauthenticated')
            active_session(repo, principal, self.clock())
            value = repo.lock_token(self.crypto.digest(token), 'verify_email')
            self._check_token(value, user.id)
            value.consumed_at = self.clock()
            first_verification = user.email_verified_at is None
            user.email_verified_at = user.email_verified_at or self.clock()
            if first_verification:
                append_domain_event(repo.session, name="email_verified", owner_id=user.owner_id,
                    domain_key=verification_key(user.owner_id), occurred_at=user.email_verified_at,
                    properties={}, environment=self.metrics_environment)
            user.updated_at = self.clock()

    def confirm_reset(self, token, password, client_ip):
        self.limiter.enforce('reset_confirm', {'ip': client_ip})
        if TOKEN_PATTERN.fullmatch(token) is None:
            raise AuthError('invalid_token')
        digest = self.crypto.digest(token)
        with auth_transaction(self.engine) as repo:
            value = repo.session.scalar(select(AuthToken).where(AuthToken.token_digest == digest, AuthToken.purpose == 'reset_password'))
            user_id = value.user_id if value else None
            self._check_token(value, user_id)
        encoded = self.passwords.hash(password)
        with auth_transaction(self.engine) as repo:
            user = repo.lock_user(user_id)
            if user is None:
                raise AuthError('invalid_token')
            value = repo.lock_token(digest, 'reset_password')
            self._check_token(value, user.id)
            value.consumed_at = self.clock()
            repo.invalidate_tokens(user.id, 'reset_password', self.clock())
            user.password_hash, user.updated_at = encoded, self.clock()
            repo.revoke_sessions(user.id, self.clock())
