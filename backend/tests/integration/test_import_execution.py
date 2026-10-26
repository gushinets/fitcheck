import asyncio
from dataclasses import replace
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import importlib
import pytest
from sqlalchemy import select,func,delete
from test_import_repository import lease_for,raw_row
from test_profile_http import profile_http
from test_import_http import payload
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job,Owner,AnalysisRecord,ProviderCall,ImportEntry,ImportItem
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.import_repository import ImportRepository,ImportLeaseLost
from fitcheck_backend.storage.job_publication import JobPublication
from fitcheck_backend.contracts.imports import parse_import_row
pytestmark=pytest.mark.integration


def executor(engine):return importlib.import_module('fitcheck_backend.imports.execution').ImportExecutor(engine)


def test_worker_queue_executes_import_and_reports_partial_errors(profile_http):
    a,c,r,issued,h=profile_http;c.app.state.settings.jobs_enabled=True
    response=c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'run'},json=payload(profile={'bad':True},locale='ru',history=[raw_row(),{'id':'bad','invalid':True}]))
    assert response.status_code==202
    reference=response.json()['importId']
    queue=JobQueue(a.engine)
    lease=queue.claim();assert lease is not None and lease.type=='import'
    assert c.get('/v1/import-jobs/'+reference).json()['progress']['totalCount']==2
    result=asyncio.run(executor(a.engine).execute(lease))
    assert result.imported_count==1 and result.invalid_count==1 and result.profile_outcome=='invalid'
    assert JobPublication(a.engine).succeed_import(lease,result)
    value=c.get('/v1/import-jobs/'+reference).json()
    assert value['status']=='succeeded' and value['report']['importedCount']==1
    detail=c.get('/v1/history').json()['items'][0]
    assert detail['snapshot']['origin']=='legacy_import' and detail['profileChanged'] is None
    with unit_of_work(a.engine) as s:assert s.scalar(select(func.count()).select_from(ProviderCall))==0


def test_recovery_reuses_committed_items_and_terminal_failure_can_resubmit(engine):
    lease=lease_for(engine,history=[raw_row(),raw_row(id='second')])
    with unit_of_work(engine) as s:
        ImportRepository(s).apply_row(lease,0,parse_import_row(raw_row()))
        job=s.get(Job,lease.job_id);job.attempts=1;job.lease_expires_at=utcnow()-timedelta(seconds=1)
    queue=JobQueue(engine);assert queue.recover_expired()==1
    recovered=queue.claim();assert recovered is not None and recovered.execution_token!=lease.execution_token
    with pytest.raises(ImportLeaseLost),unit_of_work(engine) as s:ImportRepository(s).apply_row(lease,1,parse_import_row(raw_row(id='second')))
    result=asyncio.run(executor(engine).execute(recovered))
    assert result.imported_count==2
    assert JobPublication(engine).succeed_import(recovered,result)
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(AnalysisRecord))==2
    again=lease_for(engine,owner=lease.owner_id,history=[raw_row(),raw_row(id='second')])
    replay=asyncio.run(executor(engine).execute(again));assert replay.skipped_count==2


def test_expired_lease_cannot_write_after_owner_lock_wait(engine):
    lease=lease_for(engine)
    # Clock advances while the write waits on the owner's serialization lock.
    entered=Event()
    with unit_of_work(engine) as blocking:
        blocking.scalar(select(Owner).where(Owner.id==lease.owner_id).with_for_update())
        def publish():
            entered.set()
            with unit_of_work(engine) as s:return ImportRepository(s).apply_row(lease,0,parse_import_row(raw_row()))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(publish);assert entered.wait(1)
            # Same owner lock protects lease mutation and gets released on commit.
            blocking.get(Job,lease.job_id).lease_expires_at=utcnow()-timedelta(seconds=1)
            blocking.commit()
            with pytest.raises(ImportLeaseLost):future.result(timeout=3)
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(AnalysisRecord))==0


def test_account_erase_stops_import_and_clear_removes_receipts(engine):
    lease=lease_for(engine)
    with unit_of_work(engine) as s:
        ImportRepository(s).apply_row(lease,0,parse_import_row(raw_row()))
        s.execute(delete(AnalysisRecord).where(AnalysisRecord.owner_id==lease.owner_id))
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(ImportEntry))==0
    with unit_of_work(engine) as s:s.execute(delete(Owner).where(Owner.id==lease.owner_id))
    with pytest.raises(ImportLeaseLost):asyncio.run(executor(engine).execute(lease))
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(ImportItem))==0


def test_runner_dispatches_import_without_provider_and_recovers_transient_db_error(engine,tmp_path):
    from sqlalchemy.exc import OperationalError
    from types import SimpleNamespace
    from fitcheck_backend.worker.runner import WorkerRunner
    from fitcheck_backend.worker.health import WorkerHealth
    settings=SimpleNamespace(heartbeat_seconds=30,drain_seconds=1)
    health=WorkerHealth(str(tmp_path/'health.json'),max_age=65)
    class ForbiddenProvider:
        async def execute(self,lease):raise AssertionError('Import sent to LLM')
    lease=lease_for(engine)
    runner=WorkerRunner(JobQueue(engine),ForbiddenProvider(),JobPublication(engine),settings,health,import_executor=executor(engine))
    asyncio.run(runner.process(lease))
    with unit_of_work(engine) as s:assert s.get(Job,lease.job_id).status=='succeeded'
    retry=lease_for(engine,source='bob')
    class FailingImport:
        async def execute(self,lease):raise OperationalError('temporary',{},Exception('offline'))
    runner=WorkerRunner(JobQueue(engine),ForbiddenProvider(),JobPublication(engine),settings,health,import_executor=FailingImport())
    asyncio.run(runner.process(retry))
    with unit_of_work(engine) as s:
        assert s.get(Job,retry.job_id).status=='running'
        s.get(Job,retry.job_id).lease_expires_at=utcnow()-timedelta(seconds=1)
    assert JobQueue(engine).recover_expired()==1


def test_exhausted_recovery_preserves_progress_and_concurrent_resubmission_deduplicates(engine):
    lease=lease_for(engine,history=[raw_row(),raw_row(id='two')])
    with unit_of_work(engine) as s:
        ImportRepository(s).apply_row(lease,0,parse_import_row(raw_row()))
        j=s.get(Job,lease.job_id);j.attempts=2;j.lease_expires_at=utcnow()-timedelta(seconds=1)
    assert JobQueue(engine).recover_expired()==1
    with unit_of_work(engine) as s:
        assert s.get(Job,lease.job_id).status=='failed'
        assert ImportRepository(s).report(lease.job_id,lease.owner_id).imported_count==1
    a=lease_for(engine,owner=lease.owner_id,history=[raw_row(),raw_row(id='two')])
    b=lease_for(engine,owner=lease.owner_id,history=[raw_row(),raw_row(id='two')])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda l:asyncio.run(executor(engine).execute(l)),[a,b]))
    assert sum(r.imported_count for r in results)==1
    with unit_of_work(engine) as s:assert s.scalar(select(func.count()).select_from(AnalysisRecord))==2


def test_legacy_unknown_locale_reanalysis_uses_current_account_preferences(profile_http):
    from test_profile_http import save
    a,c,r,issued,h=profile_http;c.app.state.settings.jobs_enabled=True
    assert save(c,h).status_code==200
    assert c.put('/v1/preferences',headers=h,json={'locale':'ru'}).status_code==200
    response=c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'legacy'},json=payload(history=[raw_row(profile=None)]))
    lease=JobQueue(a.engine).claim();assert lease is not None
    report=asyncio.run(executor(a.engine).execute(lease));assert JobPublication(a.engine).succeed_import(lease,report)
    item=c.get('/v1/history').json()['items'][0]
    assert item['snapshot']['profile'] is None and item['snapshot']['locale'] is None
    result=c.post('/v1/analyses/'+item['analysisId']+'/reanalyses',headers=h|{'Idempotency-Key':'new'})
    assert result.status_code==202,result.text
    with unit_of_work(a.engine) as s:
        new=s.scalar(select(Job).where(Job.type=='analysis'))
        assert new.input['locale']=='ru'


def test_shared_client_export_fixture_roundtrips_and_replays(profile_http):
    import json
    from pathlib import Path
    a,c,r,issued,h=profile_http;c.app.state.settings.jobs_enabled=True
    value=json.loads((Path(__file__).parents[3]/'contracts/fixtures/local-import-v1.json').read_text())
    def run(key):
        response=c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':key},json=value)
        assert response.status_code==202,response.text
        lease=JobQueue(a.engine).claim();assert lease is not None
        report=asyncio.run(executor(a.engine).execute(lease));assert JobPublication(a.engine).succeed_import(lease,report)
        return c.get('/v1/import-jobs/'+response.json()['importId']).json()['report']
    assert run('first')['importedCount']==1
    assert c.get('/v1/profile').json()['profile']==value['profile']
    assert c.get('/v1/preferences').json()=={'locale':'ru'}
    item=c.get('/v1/history').json()['items'][0]
    assert item['analysis']==value['history'][0]['analysis']
    assert item['snapshot']['vacancy']['url']==value['history'][0]['job']['url']
    assert item['snapshot']['evidenceProvenance']=='unverified_legacy'
    assert item['feedback']=={'correctedScore':64,'note':'Старый отзыв'}
    assert item['createdAt'].startswith('2025-01-01T00:00:00')
    assert run('second')['skippedCount']==1
    assert len(c.get('/v1/history').json()['items'])==1
