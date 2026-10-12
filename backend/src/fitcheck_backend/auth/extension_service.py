import hashlib
import hmac
import re
from datetime import timedelta
from sqlalchemy import select
from .crypto import TOKEN_PATTERN, b64
from .types import IssuedCode, IssuedSession, Principal
from .errors import AuthError
from .service import auth_transaction, active_session, principal_for
from ..storage.identity import AuthToken, AuthSession


class ExtensionAuthService:
    def __init__(self, engine, crypto, limiter, clock, redirect_uris):
        self.engine, self.crypto, self.limiter, self.clock = engine, crypto, limiter, clock
        self.redirect_uris = frozenset(redirect_uris)

    def authorize(self, principal, redirect_uri, code_challenge, state):
        if principal.kind != 'web' or redirect_uri not in self.redirect_uris or not TOKEN_PATTERN.fullmatch(code_challenge):
            raise AuthError('forbidden')
        raw, expiry = self.crypto.new_token(), self.clock() + timedelta(minutes=2)
        with auth_transaction(self.engine) as repo:
            user = repo.lock_user(principal.user_id)
            if user is None or user.owner_id != principal.owner_id:
                raise AuthError('unauthenticated')
            active_session(repo, principal, self.clock())
            if user.email_verified_at is None:
                raise AuthError('email_not_verified')
            repo.create_token(user, 'extension_code', self.crypto.digest(raw), expiry,
                issued_session_id=principal.session_id, code_challenge=code_challenge, redirect_uri=redirect_uri)
        return IssuedCode(raw, state, expiry)

    def exchange(self, code, code_verifier, redirect_uri, client_ip):
        self.limiter.enforce('extension_exchange', {'ip': client_ip})
        if not TOKEN_PATTERN.fullmatch(code) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', code_verifier) or redirect_uri not in self.redirect_uris:
            raise AuthError('invalid_token')
        digest = self.crypto.digest(code)
        with auth_transaction(self.engine) as repo:
            user_id = repo.session.scalar(select(AuthToken.user_id).where(AuthToken.token_digest == digest, AuthToken.purpose == 'extension_code'))
            if user_id is None:
                raise AuthError('invalid_token')
            user = repo.lock_user(user_id)
            value = repo.lock_token(digest, 'extension_code')
            challenge = b64(hashlib.sha256(code_verifier.encode('ascii')).digest())
            if (user is None or user.email_verified_at is None or value is None or value.consumed_at is not None
                    or value.expires_at <= self.clock() or value.redirect_uri != redirect_uri
                    or not hmac.compare_digest(challenge, value.code_challenge) or value.issued_session_id is None):
                raise AuthError('invalid_token')
            parent = repo.session.scalar(select(AuthSession).where(AuthSession.id == value.issued_session_id,
                AuthSession.user_id == user.id, AuthSession.kind == 'web', AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > self.clock()).with_for_update().execution_options(populate_existing=True))
            if parent is None:
                raise AuthError('invalid_token')
            value.consumed_at = self.clock()
            raw, expiry = self.crypto.new_token(), self.clock() + timedelta(hours=1)
            token = repo.create_session(user, 'extension', self.crypto.digest(raw), None, expiry)
            return IssuedSession(principal_for(user, token), raw, None, expiry)

    def revoke(self, principal):
        if principal.kind != 'extension':
            raise AuthError('forbidden')
        with auth_transaction(self.engine) as repo:
            user = repo.lock_user(principal.user_id)
            if user is None or user.owner_id != principal.owner_id:
                raise AuthError('unauthenticated')
            active_session(repo, principal, self.clock())
            repo.revoke_sessions(user.id, self.clock(), session_id=principal.session_id)
