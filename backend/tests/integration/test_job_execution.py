import asyncio
import json
from types import SimpleNamespace
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from analysis_fixtures import DATA
from job_fixtures import account, request
from llm_fakes import Adapter
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job, ProviderCall
from fitcheck_backend.llm.types import ProviderReply

pytestmark = pytest.mark.integration


def test_frozen_execution_releases_db_during_http_and_recovery_gets_new_operation(engine, auth_components):
    from fitcheck_backend.jobs.admission import JobAdmission
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    from fitcheck_backend.storage.job_queue import JobQueue
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    from fitcheck_backend.llm.gateway import ProviderGateway
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.analysis.executor import AnalysisExecutor
    from fitcheck_backend.analysis.service import AnalysisService
    owner, _ = account(engine)
    job = JobAdmission(engine, auth_components.limiter).start_analysis(owner_id=owner.id,
        request=request(), idempotency_key='one', client_ip='127.0.0.1')
    replies = [ProviderReply(json.dumps({**DATA['analysis'],'strengths':['skill:0']}),12,4,None,None),
        ProviderReply('{"supported":true,"unsupportedClaims":[]}',8,2,None,None)]*2
    class CheckingAdapter(Adapter):
        async def complete(self, **kwargs):
            assert engine.pool.checkedout() == 0
            await asyncio.sleep(0)
            return await super().complete(**kwargs)
    adapter = CheckingAdapter(replies)
    runtime = SimpleNamespace(analysis=AnalysisService(engine,
        AnalysisExecutor(ProviderGateway(adapter,ProviderLedger(engine))),analysis_policy()))
    q = JobQueue(engine)
    one = q.claim()
    first = asyncio.run(FrozenJobExecutor(runtime).execute(one))
    with unit_of_work(engine) as s:
        s.get(Job,job.job_id).lease_expires_at = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    q.recover_expired()
    two = q.claim()
    second = asyncio.run(FrozenJobExecutor(runtime).execute(two))
    assert first == second
    assert one.execution_token != two.execution_token
    with unit_of_work(engine) as s:
        rows = s.scalars(select(ProviderCall)).all()
        assert len(rows) == 4 and len({r.request_key.split(':')[0] for r in rows}) == 2
        assert {r.execution_token for r in rows} == {one.execution_token,two.execution_token}
        assert {(r.provider, r.model, r.policy_version) for r in rows} == {
            ('openai', 'gpt-6-luna', 'fitcheck.llm.policy.v2')}
