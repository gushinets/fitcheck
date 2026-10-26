"""0007 preserves historical costs and stores sub-cent cache-write estimates exactly."""
from fitcheck_backend.budgets.types import CallBounds
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from fitcheck_backend.storage.migrate import migration_config

pytestmark = pytest.mark.integration


def test_migration_preserves_existing_provider_usage(engine):
    old_id, new_id = uuid4(), uuid4()
    with engine.begin() as conn:
        # Run this in the disposable test database only (conftest enforces suffix).
        command.downgrade(migration_config(conn), '0006')
        conn.execute(text("INSERT INTO provider_calls(id,provider,model,operation,attempt,state,input_tokens,output_tokens,cost,currency,created_at) VALUES (:id,'deepseek','deepseek-v4-flash','analysis.generate',1,'succeeded',12,4,0.12345678,'USD',now())"), {'id':old_id})
        command.upgrade(migration_config(conn), 'head')
        row=conn.execute(text('SELECT input_tokens,output_tokens,cost,cost_basis,rate_version FROM provider_calls WHERE id=:id'), {'id':old_id}).one()
        assert tuple(row) == (12,4,Decimal('0.12345678'),None,None)
        conn.execute(text("INSERT INTO provider_calls(id,provider,model,operation,attempt,state,input_tokens,output_tokens,cached_input_tokens,cache_write_tokens,cost,currency,cost_basis,rate_version,created_at) VALUES (:id,'openai','gpt-6-luna','analysis.generate',1,'succeeded',1,0,0,1,0.000000125,'USD','estimated','openai.luna.2026-10-16',now())"), {'id':new_id})
        assert conn.scalar(text('SELECT cost FROM provider_calls WHERE id=:id'),{'id':new_id}) == Decimal('0.000000125')
        assert conn.scalar(text("SELECT numeric_scale FROM information_schema.columns WHERE table_name='website_provider_attempts' AND column_name='cost' AND table_schema=current_schema()")) == 12


def test_historical_deepseek_cost_stays_estimated(engine,storage_factory):
    from datetime import timedelta
    from fitcheck_backend.storage.database import unit_of_work
    from fitcheck_backend.storage.models import ProviderCall
    from fitcheck_backend.storage.base import utcnow
    from fitcheck_backend.metrics.queries import load_snapshot
    from fitcheck_backend.metrics.report_types import ReportOptions
    with unit_of_work(engine) as session:
        owner,_,job,_,_,_=storage_factory(session)
        call=ProviderCall(owner_id=owner.id,job_id=job.id,provider='deepseek',model='deepseek-v4-flash',
            operation='analysis.generate',attempt=1,state='succeeded',input_tokens=12,output_tokens=4,
            cost=Decimal('0.12345678'),currency='USD')
        session.add(call);session.flush();call_id=call.id
    now=utcnow()
    opt=ReportOptions(start=now-timedelta(days=1),end=now+timedelta(days=1),environment='test',population='all')
    with engine.connect() as conn:
        data=load_snapshot(conn,opt,backend_database_environment='test')
        a=next(a for a in data.attempts if a.call_id==call_id)
        assert a.cost==Decimal('0.12345678') and a.cost_basis=='estimated' and a.rate_version is None
        assert conn.scalar(text('SELECT cost_basis FROM provider_calls WHERE id=:id'),{'id':call_id}) is None


def test_failed_generation_and_audit_cost_in_successful_operation(engine,storage_factory):
    from datetime import timedelta
    from fitcheck_backend.storage.database import unit_of_work
    from fitcheck_backend.storage.provider_repository import ProviderAttempt,ProviderLedger
    from fitcheck_backend.storage.base import utcnow
    from fitcheck_backend.metrics.queries import load_snapshot
    from fitcheck_backend.metrics.report_types import ReportOptions
    from fitcheck_backend.metrics.calculations import calculate
    from fitcheck_backend.metrics.contracts import WebsiteAttempt
    from fitcheck_backend.metrics.repository import MetricRepository
    from fitcheck_backend.llm.pricing import RATE_VERSION
    with unit_of_work(engine) as session:
        owner,_,job,_,_,_=storage_factory(session)
        owner_id,job_id=owner.id,job.id
    ledger=ProviderLedger(engine)
    for ordinal,(purpose,state) in enumerate([('analysis.generate','failed'),('analysis.audit','failed'),('analysis.generate','succeeded')],1):
        call_id=ledger.start(ProviderAttempt(owner_id,job_id,uuid4(),ordinal,1,1,purpose,'openai','gpt-6-luna','p.v1','s.v1','policy.v1'),bounds=CallBounds(100,100,Decimal('.001'),'openai.luna.2026-10-16'))
        ledger.finish(call_id,state=state,input_tokens=1,output_tokens=0,cost=Decimal('0.000000125'),currency='USD',
            latency_ms=1,error_code='invalid_output' if state=='failed' else None,cached_input_tokens=0,cache_write_tokens=1,
            reasoning_tokens=0,cost_basis='estimated',rate_version=RATE_VERSION,service_tier='default',processing_region='global',response_model='gpt-6-luna')
    now=utcnow();site_id=uuid4()
    with unit_of_work(engine) as session:
        attempt=WebsiteAttempt(callId=site_id,operationId=uuid4(),subjectId=uuid4(),purpose='analysis.generate',ordinal=1,
            provider='openai',model='gpt-6-luna',promptVersion='p.v1',policyVersion='policy.v1',
            startedAt=now-timedelta(seconds=1),finishedAt=now,state='succeeded',inputTokens=1,outputTokens=0,
            cachedInputTokens=0,cacheWriteTokens=1,reasoningTokens=0,cost=Decimal('0.000000125'),currency='USD',costBasis='estimated',rateVersion=RATE_VERSION,
            serviceTier='default',processingRegion='global',responseModel='gpt-6-luna')
        MetricRepository(session).settle_attempt(attempt,environment='test')
    opt=ReportOptions(start=now-timedelta(days=1),end=now+timedelta(days=1),environment='test',population='all')
    with engine.connect() as conn:
        data=load_snapshot(conn,opt,backend_database_environment='test')
        assert len(data.attempts)==4  # Independent projections never fan out.
        assert all(a.cost==Decimal('0.000000125') and a.rate_version==RATE_VERSION for a in data.attempts)
        assert all(a.cached_input_tokens==0 and a.cache_write_tokens==1 and a.reasoning_tokens==0 for a in data.attempts)
        rows=calculate(opt,data)
        result=next(r for r in rows if r.metric=='cost_per_success' and r.dimensions.get('source')=='backend_server' and r.dimensions.get('operation')=='analysis' and r.dimensions.get('currency')=='USD')
        assert result.denominator==1 and result.numerator==Decimal('0.000000375')
        assert next(a for a in data.attempts if a.call_id==site_id).cost==Decimal('0.000000125')
