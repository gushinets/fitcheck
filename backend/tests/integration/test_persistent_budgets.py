from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import BudgetWindow
from fitcheck_backend.storage.provider_repository import ProviderLedger
from fitcheck_backend.budgets.types import CallBounds
from fitcheck_backend.quotas.policy import QuotaPolicy
from fitcheck_backend.config import Settings
from fitcheck_backend.quotas.errors import QuotaError
from test_provider_execution import attempt

pytestmark=pytest.mark.integration
BOUNDS=CallBounds(100,100,Decimal('0.001'),'openai.luna.2026-10-16')


def setup(engine,factory):
    with unit_of_work(engine) as s:
        o,_,j,*_=factory(s)
        return o.id,j.id


def test_crash_after_reserve_retains_exposure(engine,storage_factory):
    owner,job=setup(engine,storage_factory)
    ProviderLedger(engine).start(attempt(owner,job),bounds=BOUNDS)
    with unit_of_work(engine) as s:
        rows=s.scalars(select(BudgetWindow)).all()
        assert len(rows)==3
        assert all((r.calls,r.exposure_tokens,r.exposure_usd)==(1,200,Decimal('.001')) for r in rows)


def test_unknown_reply_never_refunds_money(engine,storage_factory):
    owner,job=setup(engine,storage_factory);ledger=ProviderLedger(engine)
    call=ledger.start(attempt(owner,job),bounds=BOUNDS)
    ledger.finish(call,state='unknown',input_tokens=None,output_tokens=None,cost=None,currency=None,latency_ms=1,error_code='cancelled')
    ledger.finish(call,state='succeeded',input_tokens=1,output_tokens=1,cost=Decimal('.000001'),currency='USD',latency_ms=1,error_code=None,cost_basis='estimated',rate_version=BOUNDS.rate_version,service_tier='default',processing_region='global',response_model='gpt-6-luna')
    with unit_of_work(engine) as s:assert all(r.exposure_usd==Decimal('.001') for r in s.scalars(select(BudgetWindow)))


def test_recovery_keeps_eight_call_cap(engine,storage_factory):
    owner,job=setup(engine,storage_factory);ledger=ProviderLedger(engine)
    for _ in range(8):ledger.start(attempt(owner,job),bounds=BOUNDS)
    with pytest.raises(QuotaError,match='budget_exceeded'):ledger.start(attempt(owner,job),bounds=BOUNDS)


def test_parallel_owners_share_deployment_cap(engine,storage_factory):
    first=setup(engine,storage_factory);second=setup(engine,storage_factory);barrier=Barrier(2)
    policy=replace(QuotaPolicy.from_settings(Settings()),deployment_daily_usd=Decimal('.001'))
    def send(pair):
        barrier.wait(timeout=10)
        try:ProviderLedger(engine,policy=policy).start(attempt(*pair),bounds=BOUNDS);return 'ok'
        except QuotaError as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(send,[first,second]))==['budget_exceeded','ok']


def test_known_usage_releases_excess_once(engine,storage_factory):
    owner,job=setup(engine,storage_factory);ledger=ProviderLedger(engine)
    call=ledger.start(attempt(owner,job),bounds=BOUNDS)
    kwargs=dict(state='succeeded',input_tokens=10,output_tokens=5,cost=Decimal('.000004'),currency='USD',latency_ms=1,error_code=None,cost_basis='estimated',rate_version=BOUNDS.rate_version,service_tier='default',processing_region='global',response_model='gpt-6-luna')
    ledger.finish(call,**kwargs);ledger.finish(call,**kwargs)
    with unit_of_work(engine) as s:
        assert all(r.exposure_usd==Decimal('.000004') and r.exposure_tokens==15 and r.calls==1 for r in s.scalars(select(BudgetWindow)))
