from datetime import datetime, UTC, timedelta
import pytest
from sqlalchemy import select, func
from fitcheck_backend.metrics.limits import MetricsRateLimiter
from fitcheck_backend.metrics.errors import MetricsError
from fitcheck_backend.storage.auth_limits import AuthRateBucket
pytestmark = pytest.mark.integration

def test_fixed_persisted_bridge_scope_is_bounded(engine):
    now = [datetime(2026,10,14,tzinfo=UTC)]
    limiter = MetricsRateLimiter(engine,'test',lambda:now[0])
    for _ in range(60): limiter.enforce()
    with pytest.raises(MetricsError,match='rate_limited'):
        MetricsRateLimiter(engine,'test',lambda:now[0]).enforce()
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(AuthRateBucket)) == 1
        assert conn.scalar(select(AuthRateBucket.scope)) == 'metrics:bridge:test'
    now[0] += timedelta(minutes=1)
    limiter.enforce()
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(AuthRateBucket)) == 1

# Reuse the guarded disposable PostgreSQL fixtures for this database-backed limit.
from integration.conftest import engine, clean_storage
