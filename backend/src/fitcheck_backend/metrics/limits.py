from datetime import datetime, UTC, timedelta
from hashlib import sha256
from math import ceil
from sqlalchemy import delete, select, tuple_, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from ..storage.auth_limits import AuthRateBucket
from .errors import MetricsError


class MetricsRateLimiter:
    """Shared environment budget plus visitor fairness across API/relay replicas."""
    def __init__(self, engine, environment, clock, *, aggregate_limit=1200, visitor_limit=60):
        self.engine, self.environment, self.clock = engine, environment, clock
        self.aggregate_limit, self.visitor_limit = aggregate_limit, visitor_limit

    def enforce(self, *, subjects=()):
        now = self.clock()
        window = datetime.fromtimestamp(int(now.timestamp()) // 60 * 60, UTC)
        expiry = window + timedelta(minutes=1)
        scope = f'metrics:bridge:{self.environment}'
        visitor_scope = f'metrics:visitor:{self.environment}'
        # Fixed lock identity, independent of caller input. Serialize admission, so
        # a rejected visitor cannot spend aggregate capacity or create more rows.
        lock = int.from_bytes(sha256(scope.encode()).digest()[:8], 'big', signed=True)
        digests = sorted({sha256(f'{visitor_scope}:{subject}'.encode()).hexdigest() for subject in subjects})
        rejected = False
        try:
            with self.engine.begin() as conn:
                conn.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock})
                expired = select(AuthRateBucket.scope, AuthRateBucket.subject_digest, AuthRateBucket.window_start).where(
                    AuthRateBucket.scope.in_([scope, visitor_scope]), AuthRateBucket.expires_at <= now
                ).order_by(AuthRateBucket.expires_at).limit(100).with_for_update(skip_locked=True)
                conn.execute(delete(AuthRateBucket).where(tuple_(AuthRateBucket.scope, AuthRateBucket.subject_digest,
                    AuthRateBucket.window_start).in_(expired)))
                aggregate = conn.scalar(select(AuthRateBucket.attempts).where(
                    AuthRateBucket.scope == scope, AuthRateBucket.subject_digest == '0' * 64,
                    AuthRateBucket.window_start == window)) or 0
                visitor_counts = dict(conn.execute(select(AuthRateBucket.subject_digest, AuthRateBucket.attempts).where(
                    AuthRateBucket.scope == visitor_scope, AuthRateBucket.window_start == window,
                    AuthRateBucket.subject_digest.in_(digests))).all()) if digests else {}
                rejected = aggregate >= self.aggregate_limit or any(count >= self.visitor_limit for count in visitor_counts.values())
                if not rejected:
                    for bucket_scope, digest in [(scope, '0' * 64), *[(visitor_scope, digest) for digest in digests]]:
                        stmt = insert(AuthRateBucket).values(scope=bucket_scope, subject_digest=digest,
                            window_start=window, expires_at=expiry, attempts=1)
                        conn.execute(stmt.on_conflict_do_update(
                            index_elements=['scope', 'subject_digest', 'window_start'],
                            set_={'attempts': AuthRateBucket.attempts + 1}))
        except SQLAlchemyError:
            raise MetricsError('service_unavailable') from None
        if rejected:
            raise MetricsError('rate_limited', retry_after=max(1, ceil((expiry-now).total_seconds())))
