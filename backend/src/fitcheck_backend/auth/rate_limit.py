from datetime import datetime, timezone, timedelta
from math import ceil
from sqlalchemy import select, delete, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Engine
from .crypto import AuthCrypto
from .errors import AuthError
from .types import Clock
from ..storage.auth_limits import AuthRateBucket

POLICIES = {
    'login': [('email', 10, 900), ('ip', 60, 900)],
    'register': [('ip', 5, 3600)],
    'verify_request': [('email', 3, 3600), ('ip', 20, 3600)],
    'reset_request': [('email', 3, 3600), ('ip', 20, 3600)],
    'verify_confirm': [('ip', 30, 900)],
    'reset_confirm': [('ip', 30, 900)],
    'bootstrap': [('ip', 60, 900)],
    'delete': [('user', 5, 900)],
    'extraction': [('user', 30, 60), ('ip', 120, 900)],
}


class AuthRateLimiter:
    def __init__(self, engine: Engine, crypto: AuthCrypto, clock: Clock):
        self.engine, self.crypto, self.clock = engine, crypto, clock

    def enforce(self, action: str, subjects: dict[str, str]) -> None:
        now = self.clock()
        rules = []
        for subject, limit, seconds in POLICIES[action]:
            if not subjects.get(subject):
                raise AuthError('forbidden')
            scope = action + ':' + subject
            window = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, timezone.utc)
            rules.append((scope, self.crypto.subject_digest(scope, subjects[subject]), window, window + timedelta(seconds=seconds), limit))
        retry = 0
        try:
            with self.engine.begin() as c:
                expired = select(AuthRateBucket.scope, AuthRateBucket.subject_digest, AuthRateBucket.window_start).where(
                    AuthRateBucket.expires_at <= now).order_by(AuthRateBucket.expires_at).limit(100).with_for_update(skip_locked=True)
                c.execute(delete(AuthRateBucket).where(tuple_(AuthRateBucket.scope, AuthRateBucket.subject_digest, AuthRateBucket.window_start).in_(expired)))
                for scope, digest, window, expiry, limit in sorted(rules):
                    statement = insert(AuthRateBucket).values(scope=scope, subject_digest=digest, window_start=window, expires_at=expiry, attempts=1)
                    statement = statement.on_conflict_do_update(index_elements=['scope', 'subject_digest', 'window_start'],
                        set_={'attempts': AuthRateBucket.attempts + 1}).returning(AuthRateBucket.attempts)
                    if c.scalar(statement) > limit:
                        retry = max(retry, max(1, ceil((expiry - now).total_seconds())))
        except SQLAlchemyError:
            raise AuthError('service_unavailable') from None
        if retry:
            raise AuthError('rate_limited', retry_after=retry)
