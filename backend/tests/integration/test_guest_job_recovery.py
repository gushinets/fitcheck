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
    from job_fixtures import account
    from analysis_fixtures import DATA
    from fitcheck_backend.jobs.envelope import AnalysisEnvelope,execution_versions
    from fitcheck_backend.contracts.resources import AccountAnalysisStart,AnalysisSnapshot
    from fitcheck_backend.analysis.service import AnalysisResult
    from fitcheck_backend.contracts.domain import FitAnalysis
    from fitcheck_backend.storage.models import QuotaReservation
    owner,_=account(engine)
    frozen=AnalysisEnvelope(envelopeVersion=1,request=AccountAnalysisStart(mode='account',profileRevision='1',vacancy=DATA['vacancy'],locale='en'),profile=DATA['profile'],memory=[],versions=execution_versions('analysis'))
    with unit_of_work(engine) as s:s.add(Job(owner_id=owner.id,type='analysis',input=frozen.model_dump(mode='json',by_alias=True),request_hash='a'*64,idempotency_key='old'))
    lease=JobQueue(engine).claim()
    snapshot=AnalysisSnapshot(profileRevision='1',profile=frozen.profile,vacancy=frozen.request.vacancy,locale='en',promptVersion=frozen.versions.prompt_version,schemaVersion=frozen.versions.schema_version,policyVersion=frozen.versions.policy_version)
    assert JobPublication(engine).succeed_analysis(lease,AnalysisResult(FitAnalysis.model_validate(DATA['analysis']),snapshot))
    with unit_of_work(engine) as s:assert s.scalar(select(QuotaReservation)) is None
