from dataclasses import replace
from datetime import timedelta
from uuid import uuid4
from decimal import Decimal

import pytest
from sqlalchemy import select
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import ProviderCall
from fitcheck_backend.storage.provider_repository import ProviderLedger, ProviderAttempt
from fitcheck_backend.storage.base import utcnow

pytestmark = pytest.mark.integration


def attempt(owner_id, job_id, token=None):
    return ProviderAttempt(owner_id, job_id, uuid4(), 1, 1, 1, 'analysis.generate',
        'openai', 'gpt-6-luna', 'prompt.v1', 'schema.v1', 'fitcheck.llm.policy.v2', execution_token=token)


def test_execution_token_is_nullable_for_old_calls(engine, storage_factory):
    with unit_of_work(engine) as s:
        owner, _, job, *_ = storage_factory(s)
    call = ProviderLedger(engine).start(attempt(owner.id, job.id))
    with unit_of_work(engine) as s:
        assert s.get(ProviderCall, call).execution_token is None


def test_late_finish_preserves_process_lost(engine, storage_factory):
    with unit_of_work(engine) as s:
        owner, _, job, *_ = storage_factory(s, terminal=False)
        job.status = 'running'
        job.lease_token = token = uuid4()
        job.lease_expires_at = utcnow() + timedelta(seconds=150)
    ledger = ProviderLedger(engine)
    call = ledger.start(attempt(owner.id, job.id, token))
    with unit_of_work(engine) as s:
        row = s.get(ProviderCall, call)
        row.state, row.error_code, row.finished_at = 'unknown', 'process_lost', utcnow()
    ledger.finish(call, state='succeeded', input_tokens=20, output_tokens=10,
        cost=Decimal('0.02'), currency='USD', latency_ms=40, error_code=None)
    with unit_of_work(engine) as s:
        row = s.get(ProviderCall, call)
        assert (row.state, row.error_code, row.input_tokens, row.cost) == ('unknown', 'process_lost', None, None)
        assert row.execution_token == token


def test_stale_execution_cannot_start_provider_attempt(engine, storage_factory):
    with unit_of_work(engine) as s:
        owner, _, job, *_ = storage_factory(s, terminal=False)
        job.status = 'running'
        job.lease_token = uuid4()
        job.lease_expires_at = utcnow() + timedelta(seconds=150)
    with pytest.raises(ValueError):
        ProviderLedger(engine).start(attempt(owner.id, job.id, uuid4()))
    with unit_of_work(engine) as s:
        assert s.scalars(select(ProviderCall)).all() == []


def test_upgrade_0002_preserves_old_provider_usage(engine):
    from fitcheck_backend.storage.migrate import migration_config, run_migrations
    from fitcheck_backend.config import Settings
    from alembic import command
    from sqlalchemy import text
    import os
    with engine.begin() as conn:
        command.downgrade(migration_config(conn), '0002')
        conn.execute(text("INSERT INTO provider_calls(id,provider,operation,model,attempt,state,input_tokens,cost,currency,created_at) VALUES (:id,'deepseek','analysis','old',1,'succeeded',12,0.02,'USD',now())"), {'id': uuid4()})
    run_migrations(Settings(database_url=os.environ['FITCHECK_TEST_DATABASE_URL']))
    with unit_of_work(engine) as s:
        row = s.scalar(select(ProviderCall))
        assert row.input_tokens == 12 and row.cost == Decimal('0.02')
        assert row.execution_token is None
