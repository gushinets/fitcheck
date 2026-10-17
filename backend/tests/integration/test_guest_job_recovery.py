from datetime import timedelta
from uuid import UUID
from decimal import Decimal
import pytest
from sqlalchemy import select
from test_guest_jobs_http import prepare,profile_http
from test_provider_execution import attempt
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job,GuestSessionRow,QuotaBucket
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.job_publication import JobPublication
from fitcheck_backend.storage.provider_repository import ProviderLedger
from fitcheck_backend.budgets.types import CallBounds
from fitcheck_backend.api.errors import ErrorBody
from fitcheck_backend.quotas.errors import QuotaError
from fitcheck_backend.storage.base import utcnow

pytestmark=pytest.mark.integration


def test_old_lease_cannot_settle_new_attempt(profile_http):
    a,c,r,h,body=prepare(profile_http)
    result=c.post('/v1/analysis-jobs',json=body,headers=h);assert result.status_code==202,result.text
    queue=JobQueue(a.engine);old=queue.claim()
    with unit_of_work(a.engine) as s:s.get(Job,old.job_id).lease_expires_at=utcnow()-timedelta(seconds=1)
    assert queue.recover_expired()==1
    new=queue.claim();pub=JobPublication(a.engine)
    error=ErrorBody(code='timeout',message='Timeout',requestId='test',details=[])
    assert not pub.fail(old,error)
    assert c.get('/v1/quota?mode=guest').json()['operations']['analysis']['reserved']==1
    assert pub.fail(new,error)
    assert c.get('/v1/quota?mode=guest').json()['remaining']==1


def test_expired_guest_cannot_send_again(profile_http):
    a,c,r,h,body=prepare(profile_http)
    result=c.post('/v1/analysis-jobs',json=body,headers=h);assert result.status_code==202,result.text
    lease=JobQueue(a.engine).claim()
    ledger=ProviderLedger(a.engine,clock=a.clock)
    ledger.start(attempt(lease.owner_id,lease.job_id,lease.execution_token),bounds=CallBounds(100,100,Decimal('.001'),'openai.luna.2026-10-16'))
    with unit_of_work(a.engine) as s:
        row=s.scalar(select(GuestSessionRow).where(GuestSessionRow.owner_id==lease.owner_id));row.expires_at=a.clock()-timedelta(seconds=1)
    with pytest.raises(QuotaError):ledger.start(attempt(lease.owner_id,lease.job_id,lease.execution_token),bounds=CallBounds(100,100,Decimal('.001'),'openai.luna.2026-10-16'))


def test_queued_v1_account_job_survives_0008(engine):
    import asyncio,json
    from types import SimpleNamespace
    from alembic import command
    from fitcheck_backend.storage.migrate import migration_config,run_migrations
    from fitcheck_backend.config import Settings
    from job_fixtures import account
    from analysis_fixtures import DATA
    from fitcheck_backend.jobs.envelope import AnalysisEnvelope,execution_versions
    from fitcheck_backend.jobs.execution import FrozenJobExecutor
    from fitcheck_backend.contracts.resources import AccountAnalysisStart
    from fitcheck_backend.storage.models import QuotaReservation,BudgetWindow,ProviderCall
    from fitcheck_backend.analysis.service import AnalysisService
    from fitcheck_backend.analysis.executor import AnalysisExecutor
    from fitcheck_backend.llm.gateway import ProviderGateway
    from fitcheck_backend.llm.policy import analysis_policy
    from fitcheck_backend.llm.types import ProviderReply
    from llm_fakes import Adapter
    with engine.begin() as conn:command.downgrade(migration_config(conn),'0007')
    owner,_=account(engine)
    frozen=AnalysisEnvelope(envelopeVersion=1,request=AccountAnalysisStart(mode='account',profileRevision='1',vacancy=DATA['vacancy'],locale='en'),profile=DATA['profile'],memory=[],versions=execution_versions('analysis'))
    with unit_of_work(engine) as session:
        session.add(Job(owner_id=owner.id,type='analysis',input=frozen.model_dump(mode='json',by_alias=True),request_hash='a'*64,idempotency_key='old'))
    run_migrations(Settings(database_url=engine.url.render_as_string(hide_password=False)))
    adapter=Adapter([ProviderReply(json.dumps({**DATA['analysis'],'strengths':['skill:0']}),12,4,None,None),ProviderReply('{"supported":true,"unsupportedClaims":[]}',8,2,None,None)])
    runtime=SimpleNamespace(analysis=AnalysisService(engine,AnalysisExecutor(ProviderGateway(adapter,ProviderLedger(engine))),analysis_policy()))
    lease=JobQueue(engine).claim()
    result=asyncio.run(FrozenJobExecutor(runtime).execute(lease))
    assert JobPublication(engine).succeed_analysis(lease,result)
    assert result.snapshot.profile_revision=='1' and result.snapshot.profile==frozen.profile
    assert len(adapter.calls)==2
    with unit_of_work(engine) as session:
        assert session.scalar(select(QuotaReservation)) is None
        assert session.scalar(select(BudgetWindow).where(BudgetWindow.scope=='job')).calls==2
        assert len(session.scalars(select(ProviderCall)).all())==2
