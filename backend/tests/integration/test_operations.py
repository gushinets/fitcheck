from datetime import timedelta
from uuid import uuid4
import pytest
from fitcheck_backend.operations.retention import cleanup
from fitcheck_backend.operations.monitoring import database_metrics
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Owner,Guest,User,AuthSession,AuthToken,Job,AnalysisRecord,ProviderCall,BudgetWindow,CallReservation

pytestmark=pytest.mark.integration


def test_guest_retention_keeps_claimed_active_and_not_yet_expired(engine):
    now=utcnow()
    with unit_of_work(engine) as s:
        account=Owner(kind='user');s.add(account);s.flush()
        user=User(owner_id=account.id,normalized_email='keep@example.com',password_hash='digest');s.add(user);s.flush()
        owners=[]
        for kind in ('expired','recent','active','claimed','provider'):
            owner=Owner(kind='guest');s.add(owner);s.flush();owners.append(owner.id)
            guest=Guest(owner_id=owner.id,expires_at=now-timedelta(days=31 if kind!='recent' else 1))
            if kind=='claimed':guest.claimed_by_user_id=user.id;guest.claimed_at=now-timedelta(days=1)
            s.add(guest)
            if kind=='provider':s.add(ProviderCall(owner_id=owner.id,request_key='unsettled',provider='openai',operation='analysis',model='test',attempt=1,state='started'))
            if kind=='active':s.add(Job(owner_id=owner.id,type='analysis',input={},idempotency_key='active',request_hash='a'*64))
    assert cleanup(engine,now=now)['guests']==1
    with unit_of_work(engine) as s:assert all(s.get(Owner,identifier) for identifier in owners)
    assert cleanup(engine,now=now,execute=True)['guests']==1
    with unit_of_work(engine) as s:
        assert s.get(Owner,owners[0]) is None
        assert all(s.get(Owner,identifier) for identifier in owners[1:])
        assert s.get(User,user.id) is not None


def test_terminal_job_retention_preserves_history_and_provider_accounting(engine,storage_factory):
    now=utcnow()
    with unit_of_work(engine) as s:
        owner,user,job,vacancy,analysis,_=storage_factory(s)
        job.finished_at=now-timedelta(days=31)
        call=ProviderCall(owner_id=owner.id,job_id=job.id,request_key='retained-ledger',provider='openai',operation='analysis',model='test',attempt=1,state='succeeded',cost=None,currency=None)
        s.add(call);s.flush()
        job_id,analysis_id,call_id=job.id,analysis.id,call.id
    assert cleanup(engine,now=now,execute=True)['jobs']==1
    with unit_of_work(engine) as s:
        assert s.get(Job,job_id) is None
        saved=s.get(AnalysisRecord,analysis_id)
        assert saved.job_id is None and saved.job_type is None and saved.analysis=={'sample':True}
        assert s.get(ProviderCall,call_id).job_id is None


def test_session_token_retention_is_bounded_and_does_not_delete_live_credentials(engine):
    now=utcnow()
    with unit_of_work(engine) as s:
        owner=Owner(kind='user');s.add(owner);s.flush()
        user=User(owner_id=owner.id,normalized_email='session@example.com',password_hash='digest');s.add(user);s.flush()
        ids=[]
        for age in (8,9,1):
            row=AuthSession(user_id=user.id,kind='web',token_digest=str(uuid4()),csrf_digest='proof',expires_at=now-timedelta(days=age))
            s.add(row);s.flush();ids.append(row.id)
        token=AuthToken(user_id=user.id,purpose='verify_email',token_digest='token',expires_at=now+timedelta(days=1));s.add(token)
    result=cleanup(engine,now=now,execute=True,limit=1)
    assert result['sessions']==1 and result['tokens']==0
    with unit_of_work(engine) as s:
        assert s.get(AuthSession,ids[-1]) is not None


def test_operational_database_metrics_are_aggregate_only(engine,storage_factory):
    with unit_of_work(engine) as s:
        _,_,job,_,_,_=storage_factory(s,terminal=False)
    value=database_metrics(engine)
    assert 'fitcheck_jobs{type="analysis",status="queued"} 1' in value
    assert 'fitcheck_queue_lag_seconds{type="analysis"}' in value
    assert float(next(line.split()[1] for line in value.splitlines() if line.startswith('fitcheck_provider_cost_usd_today '))) == 0
    assert 'sample' not in value and str(job.id) not in value


def test_retention_keeps_terminal_job_with_unsettled_provider_reservation(engine,storage_factory):
    from decimal import Decimal
    now=utcnow()
    with unit_of_work(engine) as s:
        owner,_,job,_,_,_=storage_factory(s)
        job.finished_at=now-timedelta(days=31)
        call=ProviderCall(owner_id=owner.id,job_id=job.id,request_key='unknown-charge',provider='openai',operation='analysis',model='test',attempt=1,state='unknown')
        window=BudgetWindow(owner_id=owner.id,scope='job',scope_key=str(job.id),window_start=now-timedelta(days=32),expires_at=now-timedelta(days=31),limit_calls=1,limit_tokens=100,limit_usd=Decimal('1'))
        s.add_all([call,window]);s.flush()
        s.add(CallReservation(provider_call_id=call.id,window_id=window.id,input_tokens=1,output_tokens=1,usd=Decimal('0.1'),rate_version='test',status='reserved'))
        job_id=job.id
    assert cleanup(engine,now=now,execute=True)['jobs']==0
    with unit_of_work(engine) as s:assert s.get(Job,job_id) is not None
