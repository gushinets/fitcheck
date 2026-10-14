from datetime import datetime, UTC, timedelta
from math import ceil
from sqlalchemy import delete, select, tuple_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from ..storage.auth_limits import AuthRateBucket
from .errors import MetricsError


class MetricsRateLimiter:
    """A fixed credential-scope bucket; callers cannot create bucket identities."""
    def __init__(self, engine, environment, clock):
        self.engine, self.environment, self.clock = engine, environment, clock

    def enforce(self):
        now = self.clock()
        window = datetime.fromtimestamp(int(now.timestamp()) // 60 * 60, UTC)
        expiry = window + timedelta(minutes=1)
        try:
            with self.engine.begin() as conn:
                expired = select(AuthRateBucket.scope, AuthRateBucket.subject_digest, AuthRateBucket.window_start).where(
                    AuthRateBucket.scope.like('metrics:bridge:%'), AuthRateBucket.expires_at <= now
                ).order_by(AuthRateBucket.expires_at).limit(100).with_for_update(skip_locked=True)
                conn.execute(delete(AuthRateBucket).where(tuple_(AuthRateBucket.scope, AuthRateBucket.subject_digest,
                    AuthRateBucket.window_start).in_(expired)))
                stmt = insert(AuthRateBucket).values(scope=f'metrics:bridge:{self.environment}',
                    subject_digest='0' * 64, window_start=window, expires_at=expiry, attempts=1)
                attempts = conn.scalar(stmt.on_conflict_do_update(
                    index_elements=['scope','subject_digest','window_start'],
                    set_={'attempts': func.least(AuthRateBucket.attempts + 1, 61)}).returning(AuthRateBucket.attempts))
        except SQLAlchemyError:
            raise MetricsError('service_unavailable') from None
        if attempts > 60:
            raise MetricsError('rate_limited', retry_after=max(1, ceil((expiry-now).total_seconds())))
