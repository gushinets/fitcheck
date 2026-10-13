from dataclasses import replace
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from datetime import timedelta
import pytest
from sqlalchemy import select, func, event
from analysis_fixtures import DATA
from job_fixtures import account, request
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job, VacancyRecord, AnalysisRecord
from fitcheck_backend.contracts.domain import FitAnalysis
from fitcheck_backend.contracts.resources import AnalysisSnapshot
from fitcheck_backend.analysis.service import AnalysisResult
from fitcheck_backend.jobs.errors import JobError

pytestmark = pytest.mark.integration


def prepared(engine, auth_components):
    from fitcheck_backend.jobs.admission import JobAdmission
    from fitcheck_backend.storage.job_queue import JobQueue
    owner, _ = account(engine)
    job = JobAdmission(engine,auth_components.limiter).start_analysis(owner_id=owner.id,
        request=request(),idempotency_key='one',client_ip='127.0.0.1')
    lease = JobQueue(engine).claim()
    snapshot = AnalysisSnapshot(profileRevision='1',profile=DATA['profile'],vacancy=DATA['vacancy'],locale='en',
        promptVersion='fitcheck.analysis.prompt.v1',schemaVersion='fitcheck.analysis.v1',policyVersion='fitcheck.llm.policy.v1')
    return lease, AnalysisResult(FitAnalysis.model_validate(DATA['analysis']),snapshot)


def publication(engine):
    from fitcheck_backend.storage.job_publication import JobPublication
    return JobPublication(engine)


def test_analysis_and_terminal_state_commit_atomically(engine,auth_components):
    lease,result = prepared(engine,auth_components)
    analysis_id = publication(engine).succeed_analysis(lease,result)
    with unit_of_work(engine) as s:
        job,analysis = s.get(Job,lease.job_id),s.get(AnalysisRecord,analysis_id)
        assert job.status == 'succeeded' and job.output is None and job.lease_token is None
        assert analysis.owner_id == lease.owner_id and analysis.job_id == lease.job_id
        assert analysis.snapshot['profileRevision'] == '1'
        assert s.scalar(select(func.count()).select_from(VacancyRecord)) == 1


def test_publication_rollback_leaves_no_vacancy_or_analysis(engine,auth_components):
    lease,result = prepared(engine,auth_components)
    def fail(conn,cursor,statement,params,context,many):
        if statement.startswith('UPDATE jobs'):
            raise RuntimeError('forced transaction failure')
    event.listen(engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError): publication(engine).succeed_analysis(lease,result)
    finally: event.remove(engine,'before_cursor_execute',fail)
    with unit_of_work(engine) as s:
        assert s.scalar(select(func.count()).select_from(VacancyRecord)) == 0
        assert s.scalar(select(func.count()).select_from(AnalysisRecord)) == 0
        assert s.get(Job,lease.job_id).status == 'running'


def test_stale_success_and_failure_cannot_publish(engine,auth_components):
    from fitcheck_backend.api.errors import ErrorBody
    lease,result = prepared(engine,auth_components)
    stale = replace(lease,execution_token=uuid4())
    value = publication(engine)
    assert value.succeed_analysis(stale,result) is None
    assert not value.fail(stale,ErrorBody(code='timeout',message='Timeout',requestId=str(lease.job_id)))
    with unit_of_work(engine) as s: assert s.get(Job,lease.job_id).status == 'running'


def test_lease_expiring_while_waiting_for_lock_cannot_publish(engine,auth_components):
    lease,result = prepared(engine,auth_components)
    attempting = Event()
    def observe(conn,cursor,statement,params,context,many):
        if 'FOR UPDATE' in statement and 'jobs' in statement: attempting.set()
    event.listen(engine,'before_cursor_execute',observe)
    try:
        with ThreadPoolExecutor(1) as pool:
            with unit_of_work(engine) as s:
                job = s.scalar(select(Job).where(Job.id == lease.job_id).with_for_update())
                attempting.clear()
                future = pool.submit(publication(engine).succeed_analysis,lease,result)
                assert attempting.wait(2)
                job.lease_expires_at = s.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
            assert future.result(timeout=5) is None
    finally: event.remove(engine,'before_cursor_execute',observe)


def test_two_publishers_create_one_analysis(engine,auth_components):
    lease,result = prepared(engine,auth_components)
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=5)
        return publication(engine).succeed_analysis(lease,result)
    with ThreadPoolExecutor(2) as pool:
        fs = [pool.submit(run) for _ in range(2)]
        outcomes = [f.result(timeout=10) for f in fs]
    assert sum(x is not None for x in outcomes) == 1
    with unit_of_work(engine) as s: assert s.scalar(select(func.count()).select_from(AnalysisRecord)) == 1


def test_owner_deleted_during_execution_has_no_partial_result(engine,auth_components):
    from fitcheck_backend.storage.ownership import delete_owner
    lease,result = prepared(engine,auth_components)
    with unit_of_work(engine) as s: delete_owner(s,lease.owner_id)
    assert publication(engine).succeed_analysis(lease,result) is None
    with unit_of_work(engine) as s: assert s.scalar(select(func.count()).select_from(AnalysisRecord)) == 0


def test_read_success_has_matching_snapshot(engine,auth_components):
    from fitcheck_backend.jobs.status import JobStatusReader
    lease,result = prepared(engine,auth_components)
    analysis_id = publication(engine).succeed_analysis(lease,result)
    state = JobStatusReader(engine).get(owner_id=lease.owner_id,job_id=lease.job_id).model_dump(mode='json')
    assert state['status'] == 'succeeded' and state['analysisId'] == str(analysis_id)
    assert state['result']['snapshot']['profileRevision'] == '1'
    assert state['result']['analysis'] == DATA['analysis']


def test_foreign_owner_get_is_not_found(engine,auth_components):
    from fitcheck_backend.jobs.status import JobStatusReader
    lease,_ = prepared(engine,auth_components)
    with pytest.raises(JobError) as exc: JobStatusReader(engine).get(owner_id=uuid4(),job_id=lease.job_id)
    assert exc.value.code == 'not_found'


def test_failure_publication_reconciles_stranded_started_call(engine,auth_components):
    from fitcheck_backend.storage.models import ProviderCall
    from fitcheck_backend.api.errors import ErrorBody
    lease,_ = prepared(engine,auth_components)
    with unit_of_work(engine) as s:
        call = ProviderCall(owner_id=lease.owner_id,job_id=lease.job_id,execution_token=lease.execution_token,
            provider='deepseek',model='test',operation='analysis.generate',attempt=1,state='started')
        s.add(call); s.flush(); call_id = call.id
    assert publication(engine).fail(lease,ErrorBody(code='timeout',message='Timeout',requestId=str(lease.job_id)))
    with unit_of_work(engine) as s:
        assert s.get(Job,lease.job_id).status == 'failed'
        row = s.get(ProviderCall,call_id)
        assert row.state == 'unknown' and row.error_code == 'execution_failed'
        assert row.finished_at is not None and row.cost is None
