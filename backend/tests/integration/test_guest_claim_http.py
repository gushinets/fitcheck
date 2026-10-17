from uuid import UUID,uuid4
import pytest
from sqlalchemy import select
from test_guest_jobs_http import prepare,profile_http
from test_guest_sessions_http import guest
from test_profile_http import WEB,DATA,save
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.base import utcnow
from fitcheck_backend.storage.models import Profile,GuestClaimReceipt,Guest,User,Job
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.job_publication import JobPublication
from fitcheck_backend.api.errors import ErrorBody

pytestmark=pytest.mark.integration


def ready(fixture):
    a,c,r,h,body=prepare(fixture)
    res=c.post('/v1/analysis-jobs',json=body,headers=h);assert res.status_code==202,res.text
    JobPublication(a.engine).fail(JobQueue(a.engine).claim(),ErrorBody(code='timeout',message='Timeout',requestId='test'))
    return a,c,r,{'Origin':WEB,'X-CSRF-Token':fixture[4]['X-CSRF-Token'],'X-Guest-CSRF-Token':h['X-CSRF-Token'],'Idempotency-Key':'claim'},body


def test_empty_account_receives_guest_profile(profile_http):
    a,c,r,h,_=ready(profile_http)
    result=c.post('/v1/guest-claims',headers=h)
    assert result.status_code==200,result.text
    assert result.json()==dict(claimedCount=0,profileImported=True)
    assert c.get('/v1/profile').json()['profile']==DATA['profile']
    assert c.post('/v1/guest-claims',headers=h).json()==result.json()
    assert c.get('/v1/quota?mode=guest').status_code==401
    assert c.get('/v1/quota?mode=account').json()['remaining']==20
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(GuestClaimReceipt)).profile_imported
        assert s.scalar(select(Guest)).claimed_by_user_id==profile_http[3].principal.user_id


def test_populated_profile_is_not_overwritten(profile_http):
    a,c,r,h,_=ready(profile_http)
    existing=save(c,profile_http[4],preferredRate=99).json()
    result=c.post('/v1/guest-claims',headers=h)
    assert result.status_code==200,result.text
    assert not result.json()['profileImported']
    assert c.get('/v1/profile').json()==existing


def test_pending_extraction_blocks_claim(profile_http):
    from fitcheck_backend.storage.quota_repository import QuotaRepository
    from fitcheck_backend.guests.sessions import guest_cookie_name
    a,c,r,h,_=ready(profile_http)
    identity=r.guests.resolve(c.cookies.get(guest_cookie_name(r.settings)))
    with unit_of_work(a.engine) as s:QuotaRepository(s).reserve_extraction(identity.owner_id,uuid4(),r.quota_policy,r.clock())
    result=c.post('/v1/guest-claims',headers=h)
    assert result.status_code==409,result.text
    assert c.get('/v1/profile').status_code==404
    with unit_of_work(a.engine) as s:assert s.scalar(select(GuestClaimReceipt)) is None


@pytest.mark.parametrize('missing',['X-CSRF-Token','X-Guest-CSRF-Token'])
def test_both_csrf_proofs_required(profile_http,missing):
    _,c,_,h,_=ready(profile_http);h.pop(missing)
    assert c.post('/v1/guest-claims',headers=h).status_code==403


def test_wrong_guest_key_and_payload_do_not_claim(profile_http):
    a,c,r,h,_=ready(profile_http)
    assert c.post('/v1/guest-claims',headers={**h,'X-Guest-CSRF-Token':'x'*43}).status_code==403
    assert c.post('/v1/guest-claims',headers=h,json={'ownerId':str(uuid4())}).status_code==400
    assert c.post('/v1/guest-claims',headers=h).status_code==200
    value,_=guest(c)
    changed=c.post('/v1/guest-claims',headers={**h,'X-Guest-CSRF-Token':value['csrfToken']})
    assert changed.status_code==409


def test_job_key_collision_rolls_back_claim(profile_http):
    a,c,r,h,_=ready(profile_http)
    with unit_of_work(a.engine) as s:
        s.add(Job(owner_id=profile_http[3].principal.owner_id,type='analysis',input={},idempotency_key='demo',request_hash='a'*64,status='failed',finished_at=utcnow(),error={'code':'timeout','message':'Timeout','requestId':'test','details':[]}))
    assert c.post('/v1/guest-claims',headers=h).status_code==409
    assert c.get('/v1/profile').status_code==404
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(GuestClaimReceipt)) is None
        assert s.scalar(select(Guest)).claimed_at is None


def test_pending_job_blocks_claim(profile_http):
    a,c,r,h,body=prepare(profile_http)
    assert c.post('/v1/analysis-jobs',json=body,headers=h).status_code==202
    headers={**h,'X-CSRF-Token':profile_http[4]['X-CSRF-Token'],'X-Guest-CSRF-Token':h['X-CSRF-Token']}
    assert c.post('/v1/guest-claims',headers=headers).status_code==409
    with unit_of_work(a.engine) as s:assert s.scalar(select(GuestClaimReceipt)) is None


def test_claim_keeps_snapshot_and_deployment_exposure(profile_http):
    from fitcheck_backend.jobs.envelope import decode_envelope
    from fitcheck_backend.analysis.service import AnalysisResult
    from fitcheck_backend.contracts.domain import FitAnalysis
    from fitcheck_backend.contracts.resources import AnalysisSnapshot
    from fitcheck_backend.storage.provider_repository import ProviderLedger
    from test_provider_execution import attempt
    from fitcheck_backend.budgets.types import CallBounds
    from fitcheck_backend.storage.models import BudgetWindow,AnalysisRecord,CallReservation
    from fitcheck_backend.auth.access import AccountDeletionService
    from decimal import Decimal
    a,c,r,h,body=prepare(profile_http)
    res=c.post('/v1/analysis-jobs',json=body,headers=h);assert res.status_code==202
    lease=JobQueue(a.engine).claim();e=decode_envelope('analysis',lease.input)
    ProviderLedger(a.engine,clock=a.clock).start(attempt(lease.owner_id,lease.job_id,lease.execution_token),bounds=CallBounds(100,100,Decimal('.001'),'openai.luna.2026-10-16'))
    snapshot=AnalysisSnapshot(profileRevision=e.profile_revision,profile=e.profile,vacancy=e.vacancy,locale=e.locale,promptVersion=e.versions.prompt_version,schemaVersion=e.versions.schema_version,policyVersion=e.versions.policy_version)
    identifier=JobPublication(a.engine).succeed_analysis(lease,AnalysisResult(FitAnalysis.model_validate(DATA['analysis']),snapshot))
    with unit_of_work(a.engine) as s:before=s.get(AnalysisRecord,identifier).snapshot
    headers={**h,'X-CSRF-Token':profile_http[4]['X-CSRF-Token'],'X-Guest-CSRF-Token':h['X-CSRF-Token']}
    result=c.post('/v1/guest-claims',headers=headers)
    assert result.status_code==200,result.text
    assert result.json()==dict(claimedCount=1,profileImported=True)
    with unit_of_work(a.engine) as s:
        record=s.get(AnalysisRecord,identifier)
        assert record.owner_id==profile_http[3].principal.owner_id and record.snapshot==before
        assert s.scalar(select(BudgetWindow).where(BudgetWindow.scope=='deployment')).exposure_usd==Decimal('.001')
    principal=r.auth.session(profile_http[3].token).principal
    AccountDeletionService(a.engine,a.passwords,a.limiter,a.clock).delete(principal,'correct horse battery')
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(BudgetWindow).where(BudgetWindow.scope=='deployment')).exposure_usd==Decimal('.001')
        assert all(w.scope=='deployment' and w.owner_id is None for w in s.scalars(select(BudgetWindow)))
        from fitcheck_backend.storage.models import ProviderCall
        assert all(p.owner_id is None and p.job_id is None for p in s.scalars(select(ProviderCall)))
        assert s.get(AnalysisRecord,identifier) is None
