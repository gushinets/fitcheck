from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import timedelta,datetime,UTC
from decimal import Decimal
import pytest
from sqlalchemy import select,event
from test_persistent_budgets import BOUNDS,setup
from test_provider_execution import attempt
from test_guest_jobs_http import prepare,profile_http
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Owner,ProviderCall,BudgetWindow,GuestSessionRow
from fitcheck_backend.storage.provider_repository import ProviderLedger
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.quotas.errors import QuotaError

pytestmark=pytest.mark.integration
KNOWN=dict(state='succeeded',input_tokens=10,output_tokens=5,cost=Decimal('.000004'),currency='USD',latency_ms=1,error_code=None,cost_basis='estimated',rate_version=BOUNDS.rate_version,service_tier='default',processing_region='global',response_model='gpt-6-luna')


def test_recovery_during_finish_owner_wait_never_refunds(engine,storage_factory):
    owner,job=setup(engine,storage_factory);ledger=ProviderLedger(engine)
    identifier=ledger.start(attempt(owner,job),bounds=BOUNDS);waiting=Event()
    def observe(conn,cursor,sql,params,context,many):
        if 'FROM owners' in sql and 'FOR UPDATE' in sql:waiting.set()
    with ThreadPoolExecutor(1) as pool:
        with unit_of_work(engine) as s:
            s.scalar(select(Owner).where(Owner.id==owner).with_for_update())
            event.listen(engine,'before_cursor_execute',observe)
            try:
                future=pool.submit(ledger.finish,identifier,**KNOWN)
                assert waiting.wait(3)
                row=s.get(ProviderCall,identifier)
                row.state,row.error_code,row.finished_at='unknown','process_lost',utcnow()
            finally:event.remove(engine,'before_cursor_execute',observe)
        future.result(timeout=10)
    with unit_of_work(engine) as s:
        assert s.get(ProviderCall,identifier).error_code=='process_lost'
        assert all(w.exposure_usd==BOUNDS.usd and w.exposure_tokens==200 for w in s.scalars(select(BudgetWindow)))


def test_provider_admission_rechecks_session_after_owner_wait(profile_http):
    a,c,r,h,body=prepare(profile_http)
    assert c.post('/v1/analysis-jobs',json=body,headers=h).status_code==202
    lease=JobQueue(a.engine).claim();ledger=ProviderLedger(a.engine,clock=a.clock);waiting=Event()
    with unit_of_work(a.engine) as s:s.scalar(select(GuestSessionRow).where(GuestSessionRow.owner_id==lease.owner_id)).expires_at=a.clock()+timedelta(seconds=1)
    def observe(conn,cursor,sql,params,context,many):
        if 'FROM owners' in sql and 'FOR UPDATE' in sql:waiting.set()
    with ThreadPoolExecutor(1) as pool:
        with unit_of_work(a.engine) as s:
            s.scalar(select(Owner).where(Owner.id==lease.owner_id).with_for_update())
            event.listen(a.engine,'before_cursor_execute',observe)
            try:
                future=pool.submit(ledger.start,attempt(lease.owner_id,lease.job_id,lease.execution_token),bounds=BOUNDS)
                assert waiting.wait(3)
                a.now[0]+=timedelta(seconds=2)
            finally:event.remove(a.engine,'before_cursor_execute',observe)
        with pytest.raises(QuotaError):future.result(timeout=10)
    with unit_of_work(a.engine) as s:assert s.scalar(select(ProviderCall)) is None


def test_provider_admission_uses_new_day_after_window_wait(engine,storage_factory):
    one=setup(engine,storage_factory);two=setup(engine,storage_factory)
    now=[datetime(2026,1,1,23,59,59,tzinfo=UTC)];ledger=ProviderLedger(engine,clock=lambda:now[0])
    ledger.start(attempt(*one),bounds=BOUNDS);waiting=Event()
    def observe(conn,cursor,sql,params,context,many):
        if sql.startswith('INSERT INTO budget_windows'):waiting.set()
    with ThreadPoolExecutor(1) as pool:
        with unit_of_work(engine) as s:
            s.scalar(select(BudgetWindow).where(BudgetWindow.scope=='deployment').with_for_update())
            event.listen(engine,'before_cursor_execute',observe)
            try:
                future=pool.submit(ledger.start,attempt(*two),bounds=BOUNDS)
                assert waiting.wait(3)
                now[0]+=timedelta(seconds=2)
            finally:event.remove(engine,'before_cursor_execute',observe)
        identifier=future.result(timeout=10)
    with unit_of_work(engine) as s:
        windows=s.scalars(select(BudgetWindow).where(BudgetWindow.scope=='deployment').order_by(BudgetWindow.window_start)).all()
        assert len(windows)==2
        assert [w.calls for w in windows]==[1,1]
        assert windows[1].window_start==datetime(2026,1,2,tzinfo=UTC)


def test_provider_admission_rechecks_lease_after_window_wait(engine,storage_factory):
    from uuid import uuid4
    from fitcheck_backend.storage.models import Job
    one=setup(engine,storage_factory);two=setup(engine,storage_factory)
    now=[utcnow()];ledger=ProviderLedger(engine,clock=lambda:now[0]);token=uuid4()
    ledger.start(attempt(*one),bounds=BOUNDS);waiting=Event()
    with unit_of_work(engine) as s:
        job=s.get(Job,two[1]);job.status='running';job.finished_at=None
        job.lease_token=token;job.lease_expires_at=now[0]+timedelta(seconds=1)
    def observe(conn,cursor,sql,params,context,many):
        if sql.startswith('INSERT INTO budget_windows'):waiting.set()
    with ThreadPoolExecutor(1) as pool:
        with unit_of_work(engine) as s:
            s.scalar(select(BudgetWindow).where(BudgetWindow.scope=='deployment').with_for_update())
            event.listen(engine,'before_cursor_execute',observe)
            try:
                future=pool.submit(ledger.start,attempt(*two,token),bounds=BOUNDS)
                assert waiting.wait(3)
                now[0]+=timedelta(seconds=2)
            finally:event.remove(engine,'before_cursor_execute',observe)
        with pytest.raises(ValueError,match='execution lease'):future.result(timeout=10)
    with unit_of_work(engine) as s:assert len(s.scalars(select(ProviderCall)).all())==1
