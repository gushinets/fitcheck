import asyncio
import json
from decimal import Decimal
from datetime import timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select,func,event
from analysis_fixtures import DATA
from job_fixtures import account,request
from llm_fakes import Adapter
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job,AnalysisRecord,ProviderCall
from fitcheck_backend.llm.types import ProviderReply

pytestmark = pytest.mark.integration


@pytest.mark.parametrize('phase',['after_claim','before_publication','during_commit'])
def test_worker_crash_recovers_once_and_preserves_repeat_cost(engine,auth_components,phase):
    from fitcheck_backend.jobs.admission import JobAdmission
    from fitcheck_backend.storage.job_queue import JobQueue
    from fitcheck_backend.storage.job_publication import JobPublication
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    from fitcheck_backend.llm.gateway import ProviderGateway
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.analysis.service import AnalysisService
    from fitcheck_backend.analysis.executor import AnalysisExecutor
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    from fitcheck_backend.worker.runner import WorkerRunner
    from fitcheck_backend.worker.health import WorkerHealth
    from fitcheck_backend.worker.settings import WorkerSettings
    owner,_ = account(engine)
    reference = JobAdmission(engine,auth_components.limiter).start_analysis(owner_id=owner.id,
        request=request(),idempotency_key='one',client_ip='127.0.0.1')
    replies = [ProviderReply(json.dumps({**DATA['analysis'],'strengths':['skill:0']}),12,4,Decimal('0.01'),'USD'),
        ProviderReply('{"supported":true,"unsupportedClaims":[]}',8,2,Decimal('0.01'),'USD')]*2
    adapter = Adapter(replies)
    runtime = SimpleNamespace(analysis=AnalysisService(engine,AnalysisExecutor(ProviderGateway(adapter,ProviderLedger(engine))),analysis_policy()))
    class Health:
        def mark(self): pass
        def clear(self): pass
    q,pub = JobQueue(engine),JobPublication(engine)
    settings = WorkerSettings()
    runner = WorkerRunner(q,FrozenJobExecutor(runtime),pub,settings,Health())
    first = q.claim()
    if phase == 'before_publication':
        asyncio.run(FrozenJobExecutor(runtime).execute(first))
    if phase == 'during_commit':
        def crash(conn,cursor,statement,params,context,many):
            if statement.startswith('UPDATE jobs'): raise RuntimeError('process stopped before commit')
        event.listen(engine,'before_cursor_execute',crash)
        try:
            with pytest.raises(RuntimeError): asyncio.run(runner.process(first))
        finally: event.remove(engine,'before_cursor_execute',crash)
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(AnalysisRecord)) == 0
        s.get(Job,reference.job_id).lease_expires_at = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    q.recover_expired()
    second = q.claim()
    runner = WorkerRunner(q,FrozenJobExecutor(runtime),pub,settings,Health())
    asyncio.run(runner.process(second))
    with unit_of_work(engine) as s:
        assert s.get(Job,reference.job_id).status == 'succeeded'
        assert s.scalar(select(func.count()).select_from(AnalysisRecord)) == 1
        calls = s.scalars(select(ProviderCall)).all()
        expected_calls = 2 if phase == 'after_claim' else 4
        assert len(adapter.calls) == len(calls) == expected_calls
        assert sum(c.cost for c in calls) == Decimal('0.01')*expected_calls
        assert len({c.request_key.split(':')[0] for c in calls}) == expected_calls//2
    assert q.claim() is None


def test_second_worker_loss_does_not_execute_third_attempt(engine,auth_components):
    from fitcheck_backend.jobs.admission import JobAdmission
    from fitcheck_backend.storage.job_queue import JobQueue
    owner,_ = account(engine)
    reference = JobAdmission(engine,auth_components.limiter).start_analysis(owner_id=owner.id,
        request=request(),idempotency_key='one',client_ip='127.0.0.1')
    q = JobQueue(engine)
    for _ in range(2):
        assert q.claim() is not None
        with unit_of_work(engine) as s:
            s.get(Job,reference.job_id).lease_expires_at = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        q.recover_expired()
    assert q.claim() is None
    with unit_of_work(engine) as s:
        assert s.get(Job,reference.job_id).status == 'failed'
        assert s.scalar(select(func.count()).select_from(ProviderCall)) == 0
