from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import select, text, func
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job, ProviderCall
from job_fixtures import account

pytestmark = pytest.mark.integration


def queued(engine, owner=None, kind='analysis'):
    if owner is None:
        owner, _ = account(engine)
    with unit_of_work(engine) as s:
        row = Job(owner_id=owner.id, type=kind, input={}, idempotency_key=str(uuid4()), request_hash='a'*64)
        s.add(row); s.flush()
    return row


def expire(engine, job_id):
    with unit_of_work(engine) as s:
        s.get(Job, job_id).lease_expires_at = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)


def queue(engine):
    from fitcheck_backend.storage.job_queue import JobQueue
    return JobQueue(engine)


def test_two_workers_claim_one_execution(engine):
    row = queued(engine)
    q = queue(engine)
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=5)
        return q.claim()
    with ThreadPoolExecutor(2) as pool:
        fs = [pool.submit(run) for _ in range(2)]
        winners = [x for f in fs if (x := f.result(timeout=10)) is not None]
    assert len(winners) == 1 and winners[0].job_id == row.id
    assert winners[0].attempts == 1


def test_locked_candidate_is_skipped(engine):
    one = queued(engine)
    two = queued(engine)
    with unit_of_work(engine) as s:
        s.scalar(select(Job).where(Job.id == one.id).with_for_update())
        assert queue(engine).claim().job_id == two.id


def test_heartbeat_cannot_resurrect_expired_lease(engine):
    q = queue(engine)
    row = queued(engine)
    lease = q.claim()
    assert q.heartbeat(lease)
    expire(engine, row.id)
    assert not q.heartbeat(lease)


def test_stale_token_cannot_heartbeat(engine):
    from dataclasses import replace
    queued(engine)
    q = queue(engine)
    lease = q.claim()
    assert not q.heartbeat(replace(lease, execution_token=uuid4()))


def test_recovery_requeues_once_then_fails(engine):
    row = queued(engine)
    q = queue(engine)
    first = q.claim()
    expire(engine, row.id)
    assert q.recover_expired() == 1
    second = q.claim()
    assert second.attempts == 2 and second.execution_token != first.execution_token
    expire(engine, row.id)
    assert q.recover_expired() == 1
    assert q.claim() is None
    with unit_of_work(engine) as s:
        result = s.get(Job, row.id)
        assert result.status == 'failed' and result.finished_at is not None
        assert result.attempts == 2 and result.lease_token is None


def test_recovery_preserves_succeeded_provider_usage(engine):
    row = queued(engine)
    q = queue(engine)
    lease = q.claim()
    with unit_of_work(engine) as s:
        call = ProviderCall(owner_id=row.owner_id, job_id=row.id, execution_token=lease.execution_token,
            provider='openai', model='gpt-6-luna', operation='analysis', attempt=1, state='succeeded',
            cost=Decimal('0.02'), currency='USD', input_tokens=12)
        s.add(call); s.flush(); call_id = call.id
    expire(engine, row.id); q.recover_expired()
    with unit_of_work(engine) as s:
        result = s.get(ProviderCall, call_id)
        assert result.state == 'succeeded' and result.cost == Decimal('0.02') and result.input_tokens == 12


def test_recovery_scopes_started_calls_to_old_token(engine):
    row = queued(engine)
    q = queue(engine)
    lease = q.claim()
    other_token = uuid4()
    with unit_of_work(engine) as s:
        for token in (lease.execution_token, other_token):
            s.add(ProviderCall(owner_id=row.owner_id, job_id=row.id, execution_token=token,
                provider='openai', model='gpt-6-luna', operation='analysis', attempt=1, state='started'))
    expire(engine, row.id); q.recover_expired()
    with unit_of_work(engine) as s:
        calls = {c.execution_token: c for c in s.scalars(select(ProviderCall))}
        assert calls[lease.execution_token].state == 'unknown'
        assert calls[lease.execution_token].error_code == 'process_lost'
        assert calls[other_token].state == 'started'


def test_import_jobs_are_claimed(engine):
    queued(engine, kind='import')
    assert queue(engine).claim().type == 'import'
