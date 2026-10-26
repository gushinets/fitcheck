from datetime import datetime, UTC, timedelta
import pytest
from sqlalchemy import select, func
from fitcheck_backend.metrics.limits import MetricsRateLimiter
from fitcheck_backend.metrics.errors import MetricsError
from fitcheck_backend.storage.auth_limits import AuthRateBucket
pytestmark = pytest.mark.integration

def test_fixed_persisted_bridge_scope_is_bounded(engine):
    now = [datetime(2026,10,14,tzinfo=UTC)]
    limiter = MetricsRateLimiter(engine,'test',lambda:now[0], aggregate_limit=60)
    for _ in range(60): limiter.enforce()
    with pytest.raises(MetricsError,match='rate_limited'):
        MetricsRateLimiter(engine,'test',lambda:now[0], aggregate_limit=60).enforce()
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(AuthRateBucket)) == 1
        assert conn.scalar(select(AuthRateBucket.scope)) == 'metrics:bridge:test'
    now[0] += timedelta(minutes=1)
    limiter.enforce()
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(AuthRateBucket)) == 1

# Reuse the guarded disposable PostgreSQL fixtures for this database-backed limit.
from integration.conftest import engine, clean_storage


def test_normal_31_visitor_traffic_fits_shared_default_capacity(engine):
    from uuid import uuid4
    now = datetime(2026, 10, 25, tzinfo=UTC)
    # Separate objects represent different API workers using the same database.
    workers = [MetricsRateLimiter(engine, 'test', lambda: now) for _ in range(2)]
    for _ in range(31):
        subject = uuid4()
        for request in range(4):
            workers[request % 2].enforce(subjects=[subject])
    with engine.connect() as conn:
        assert conn.scalar(select(AuthRateBucket.attempts).where(AuthRateBucket.scope == 'metrics:bridge:test')) == 124


def test_rejected_visitor_cannot_consume_others_shared_budget(engine):
    from uuid import uuid4
    now = datetime(2026, 10, 25, tzinfo=UTC)
    workers = [MetricsRateLimiter(engine, 'test', lambda: now) for _ in range(2)]
    noisy, normal = uuid4(), uuid4()
    for i in range(60):
        workers[i % 2].enforce(subjects=[noisy])
    for _ in range(65):
        with pytest.raises(MetricsError, match='rate_limited') as error:
            workers[1].enforce(subjects=[noisy])
        assert error.value.retry_after == 60
    workers[0].enforce(subjects=[normal])
    with engine.connect() as conn:
        assert conn.scalar(select(AuthRateBucket.attempts).where(AuthRateBucket.scope == 'metrics:bridge:test')) == 61


def test_replicas_share_aggregate_limit_and_deduplicate_subjects_per_request(engine):
    from uuid import uuid4
    now = [datetime(2026, 10, 25, tzinfo=UTC)]
    workers = [MetricsRateLimiter(engine, 'test', lambda: now[0], aggregate_limit=4, visitor_limit=2) for _ in range(2)]
    a, b = uuid4(), uuid4()
    workers[0].enforce(subjects=[a, a])
    workers[1].enforce(subjects=[a])
    workers[0].enforce(subjects=[b])
    workers[1].enforce(subjects=[b])
    with pytest.raises(MetricsError, match='rate_limited'):
        workers[0].enforce(subjects=[uuid4()])
    now[0] += timedelta(seconds=61)
    workers[1].enforce(subjects=[a])
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(AuthRateBucket)) == 2


def test_concurrent_workers_cannot_exceed_shared_capacity(engine):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    now = datetime(2026, 10, 25, tzinfo=UTC)
    def admit(_):
        try:
            MetricsRateLimiter(engine, 'test', lambda: now, aggregate_limit=4).enforce(subjects=[uuid4()])
            return True
        except MetricsError as error:
            assert error.code == 'rate_limited'
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(admit, range(12))) == 4
    with engine.connect() as conn:
        # One aggregate plus four admitted visitor rows. Rejections add no rows.
        assert conn.scalar(select(func.count()).select_from(AuthRateBucket)) == 5
