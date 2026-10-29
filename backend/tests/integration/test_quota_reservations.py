from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime,UTC,timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job,QuotaBucket
from fitcheck_backend.quotas.policy import QuotaPolicy
from fitcheck_backend.config import Settings

pytestmark=pytest.mark.integration


def fixture_jobs(engine,storage_factory):
    with unit_of_work(engine) as s:
        graph=storage_factory(s,kind='guest')
        owner=graph[0].id
        jobs=[]
        for _ in range(2):
            job=Job(owner_id=owner,type='analysis',input={},request_hash='a'*64,idempotency_key=str(uuid4()))
            s.add(job);s.flush();jobs.append(job.id)
        return owner,jobs


def test_one_remaining_slot_has_one_winner(engine,storage_factory):
    from fitcheck_backend.storage.quota_repository import QuotaRepository
    from fitcheck_backend.quotas.errors import QuotaError
    owner,jobs=fixture_jobs(engine,storage_factory);barrier=Barrier(2)
    policy=QuotaPolicy.from_settings(Settings())
    def reserve(i):
        barrier.wait(timeout=10)
        try:
            with unit_of_work(engine) as s:QuotaRepository(s).reserve_job(owner,jobs[i],'analysis',policy,datetime.now(UTC))
            return 'admitted'
        except QuotaError as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,[0,1]))
    assert sorted(results)==['admitted','quota_exceeded']
    with unit_of_work(engine) as s:
        bucket=s.scalar(select(QuotaBucket).where(QuotaBucket.owner_id==owner))
        assert (bucket.reserved,bucket.consumed,bucket.limit)==(1,0,1)


def test_job_refund_and_success_are_idempotent(engine,storage_factory):
    from fitcheck_backend.storage.quota_repository import QuotaRepository
    owner,jobs=fixture_jobs(engine,storage_factory);policy=QuotaPolicy.from_settings(Settings());now=datetime.now(UTC)
    with unit_of_work(engine) as s:
        repo=QuotaRepository(s);repo.reserve_job(owner,jobs[0],'analysis',policy,now)
        assert repo.settle_job(jobs[0],success=False,now=now)
        assert not repo.settle_job(jobs[0],success=False,now=now)
        repo.reserve_job(owner,jobs[1],'analysis',policy,now)
        assert repo.settle_job(jobs[1],success=True,now=now)
        assert not repo.settle_job(jobs[1],success=False,now=now)
        bucket=s.scalar(select(QuotaBucket).where(QuotaBucket.owner_id==owner))
        assert (bucket.reserved,bucket.consumed)==(0,1)


def test_settlement_uses_original_midnight_window(engine,storage_factory):
    from fitcheck_backend.storage.quota_repository import QuotaRepository
    policy=QuotaPolicy.from_settings(Settings())
    with unit_of_work(engine) as s:
        owner=storage_factory(s)[0].id
        job=Job(owner_id=owner,type='analysis',input={},request_hash='a'*64,idempotency_key='midnight')
        s.add(job);s.flush();identifier=job.id
        repo=QuotaRepository(s);now=datetime(2026,1,1,23,59,tzinfo=UTC)
        repo.reserve_job(owner,identifier,'analysis',policy,now)
        following=repo.bucket(owner,'analysis',policy,now+timedelta(minutes=2))
        assert repo.settle_job(identifier,success=True,now=now+timedelta(minutes=2))
        assert following.consumed==0 and following.reserved==0


def test_expired_extraction_is_reaped_once_and_cannot_settle(engine,storage_factory):
    from fitcheck_backend.storage.quota_repository import QuotaRepository
    policy=QuotaPolicy.from_settings(Settings());now=datetime.now(UTC)
    with unit_of_work(engine) as s:
        owner=storage_factory(s,kind='guest')[0].id;repo=QuotaRepository(s);identifier=uuid4()
        repo.reserve_extraction(owner,identifier,policy,now)
        assert repo.reap_extractions(now+timedelta(seconds=121))==1
        assert repo.reap_extractions(now+timedelta(seconds=121))==0
        assert not repo.settle_extraction(identifier,success=True,now=now+timedelta(seconds=122))
        bucket=repo.bucket(owner,'extraction',policy,now)
        assert bucket.reserved==0 and bucket.consumed==0


def test_unlimited_account_analyses_preserve_usage_and_can_be_limited_again(engine,storage_factory):
    from fitcheck_backend.storage.quota_repository import QuotaRepository
    from fitcheck_backend.quotas.errors import QuotaError
    now=datetime.now(UTC)
    unlimited=QuotaPolicy.from_settings(Settings(account_analysis_daily_limit=0))
    limited=QuotaPolicy.from_settings(Settings(account_analysis_daily_limit=1))
    with unit_of_work(engine) as s:
        owner=storage_factory(s)[0].id
        repo=QuotaRepository(s)
        jobs=[]
        for index in range(26):
            job=Job(owner_id=owner,type='analysis',input={},request_hash='a'*64,idempotency_key=f'unlimited-{index}')
            s.add(job);s.flush();jobs.append(job.id)
        repo.reserve_job(owner,jobs[0],'analysis',limited,now)
        repo.settle_job(jobs[0],success=True,now=now)
        for job_id in jobs[1:25]:
            repo.reserve_job(owner,job_id,'analysis',unlimited,now)
            repo.settle_job(job_id,success=True,now=now)
        bucket=repo.bucket(owner,'analysis',unlimited,now)
        assert bucket.limit is None and bucket.consumed==25 and bucket.reserved==0
        with pytest.raises(QuotaError,match='quota_exceeded'):
            repo.reserve_job(owner,jobs[25],'analysis',limited,now)
        assert bucket.consumed==25 and bucket.limit==25
        repo.reserve_job(owner,jobs[25],'analysis',unlimited,now)
        assert bucket.limit is None and bucket.reserved==1
        assert repo.settle_job(jobs[25],success=False,now=now)
        assert bucket.consumed==25 and bucket.reserved==0


def test_unlimited_bucket_still_rejects_negative_usage(engine,storage_factory):
    from sqlalchemy.exc import IntegrityError
    from fitcheck_backend.storage.quota_repository import QuotaRepository
    policy=QuotaPolicy.from_settings(Settings(account_analysis_daily_limit=0))
    with unit_of_work(engine) as s:
        owner=storage_factory(s)[0].id
        bucket=QuotaRepository(s).bucket(owner,'analysis',policy,datetime.now(UTC))
        with pytest.raises(IntegrityError),s.begin_nested():
            bucket.reserved=-1
            s.flush()
