import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from fitcheck_backend.config import Settings
from fitcheck_backend.storage.database import create_engine, unit_of_work
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.models import Owner, User, Guest, Job, VacancyRecord, AnalysisRecord, AnalysisAnnotation


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("FITCHECK_TEST_DATABASE_URL")
    if not url:
        pytest.fail("FITCHECK_TEST_DATABASE_URL is required for integration tests")
    from sqlalchemy.engine import make_url
    if not make_url(url).database.endswith("_test"):
        pytest.fail("Integration database name must end in _test")
    from fitcheck_backend.storage.migrate import run_migrations
    settings = Settings(database_url=url, pool_size=5, max_overflow=5)
    run_migrations(settings)
    value = create_engine(settings)
    yield value
    value.dispose()


@pytest.fixture(autouse=True)
def clean_storage(request):
    if request.node.get_closest_marker("integration") is None:
        return
    engine = request.getfixturevalue("engine")
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE owners, provider_calls, auth_rate_buckets, metric_journal, website_provider_attempts, metric_collections, metric_erased_visitors CASCADE"))


@pytest.fixture
def db_session(engine):
    with unit_of_work(engine) as session:
        yield session


@pytest.fixture
def storage_factory():
    def build(session, *, kind="user", job_type="analysis", terminal=True):
        owner = Owner(id=uuid4(), kind=kind)
        session.add(owner)
        session.flush()
        if kind == "user":
            identity = User(owner_id=owner.id, normalized_email=f"{owner.id}@example.com", password_hash="hashed")
        else:
            identity = Guest(owner_id=owner.id, expires_at=utcnow() + timedelta(days=1))
        session.add(identity)
        session.flush()
        job = Job(id=uuid4(), owner_id=owner.id, type=job_type, input={"sample": True}, idempotency_key=str(uuid4()), request_hash="a" * 64, status="succeeded" if terminal else "queued", finished_at=utcnow() if terminal else None, output={"skills": []} if job_type == "skill_suggestions" and terminal else {"importedCount": 0} if job_type == "import" and terminal else None)
        vacancy = VacancyRecord(id=uuid4(), owner_id=owner.id, vacancy={"sample": True})
        session.add_all([job, vacancy])
        session.flush()
        analysis = AnalysisRecord(id=uuid4(), owner_id=owner.id, job_id=job.id if job_type == "analysis" else None, job_type="analysis" if job_type == "analysis" else None, vacancy_id=vacancy.id, snapshot={"sample": True}, analysis={"sample": True})
        session.add(analysis)
        session.flush()
        annotation = AnalysisAnnotation(owner_id=owner.id, analysis_id=analysis.id)
        session.add(annotation)
        session.flush()
        return owner, identity, job, vacancy, analysis, annotation
    return build


@pytest.fixture
def auth_components(engine):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from argon2 import PasswordHasher
    from fitcheck_backend.auth.crypto import AuthCrypto
    from fitcheck_backend.auth.passwords import PasswordCodec
    from fitcheck_backend.auth.rate_limit import AuthRateLimiter
    from fitcheck_backend.auth.mail import MailDeliveryError
    from fitcheck_backend.auth.service import AuthService
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    clock = lambda: now[0]
    crypto = AuthCrypto(b'x' * 32, clock)
    passwords = PasswordCodec(hasher=PasswordHasher(memory_cost=8192, time_cost=1, parallelism=1))
    limiter = AuthRateLimiter(engine, crypto, clock)
    class CapturingMailer:
        enabled = True
        fail = False
        def __init__(self):
            self.messages = []
        def available(self):
            return self.enabled
        def send(self, message):
            if self.fail:
                raise MailDeliveryError()
            self.messages.append(message)
    mailer = CapturingMailer()
    service = AuthService(engine, crypto, passwords, limiter, mailer, clock)
    return SimpleNamespace(engine=engine, now=now, clock=clock, crypto=crypto, passwords=passwords, limiter=limiter, mailer=mailer, service=service)
