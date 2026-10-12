from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import select, func
from fitcheck_backend.auth.crypto import AuthCrypto
from fitcheck_backend.auth.errors import AuthError
from fitcheck_backend.auth.rate_limit import AuthRateLimiter
from fitcheck_backend.storage.auth_limits import AuthRateBucket
from fitcheck_backend.storage.database import unit_of_work

pytestmark = pytest.mark.integration


def test_limiter_two_connections_admit_exact_budget(engine):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    limiter = AuthRateLimiter(engine, AuthCrypto(b'x' * 32, lambda: now), lambda: now)
    barrier = Barrier(16)
    def attempt():
        barrier.wait(10)
        try:
            limiter.enforce('login', {'email': 'a@example.com', 'ip': '192.0.2.1'})
            return True
        except AuthError as exc:
            assert exc.code == 'rate_limited' and 1 <= exc.retry_after <= 900
            return False
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(lambda _: attempt(), range(16))) == 10
    with unit_of_work(engine) as s:
        assert sorted(s.scalars(select(AuthRateBucket.attempts))) == [16, 16]


def test_limiter_window_expiry_and_hmac_privacy(engine):
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    limiter = AuthRateLimiter(engine, AuthCrypto(b'x' * 32, lambda: now[0]), lambda: now[0])
    for _ in range(10):
        limiter.enforce('login', {'email': 'a@example.com', 'ip': '192.0.2.1'})
    with pytest.raises(AuthError):
        limiter.enforce('login', {'email': 'a@example.com', 'ip': '192.0.2.1'})
    now[0] += timedelta(seconds=900)
    limiter.enforce('login', {'email': 'a@example.com', 'ip': '192.0.2.1'})
    with unit_of_work(engine) as s:
        rows = s.scalars(select(AuthRateBucket)).all()
        assert [r.attempts for r in rows] == [1, 1]
        assert all('example' not in r.subject_digest and '192.' not in r.subject_digest for r in rows)
        for i in range(150):
            s.add(AuthRateBucket(scope=f'expired-{i}', subject_digest='0' * 64, window_start=now[0]-timedelta(hours=2), expires_at=now[0]-timedelta(hours=1), attempts=1))
    limiter.enforce('bootstrap', {'ip': '192.0.2.1'})
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(AuthRateBucket).where(AuthRateBucket.expires_at <= now[0])) == 50


def test_rate_admission_survives_service_rollback(engine):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    limiter = AuthRateLimiter(engine, AuthCrypto(b'x' * 32, lambda: now), lambda: now)
    with pytest.raises(RuntimeError):
        with unit_of_work(engine):
            limiter.enforce('register', {'ip': '192.0.2.1'})
            raise RuntimeError('business failure')
    with unit_of_work(engine) as s:
        assert s.scalar(select(AuthRateBucket.attempts)) == 1


def test_retry_after_rounds_fractional_seconds_up(engine):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=100)
    limiter = AuthRateLimiter(engine, AuthCrypto(b'x' * 32, lambda: now), lambda: now)
    for _ in range(10):
        limiter.enforce('login', {'email': 'a@example.com', 'ip': '192.0.2.1'})
    with pytest.raises(AuthError) as exc:
        limiter.enforce('login', {'email': 'a@example.com', 'ip': '192.0.2.1'})
    assert exc.value.retry_after == 900
