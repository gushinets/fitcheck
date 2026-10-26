from uuid import UUID
import pytest
from sqlalchemy import select,func
from test_guest_sessions_http import profile_http,guest
from test_profile_http import WEB,DATA
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job,QuotaReservation
from fitcheck_backend.storage.job_queue import JobQueue
from fitcheck_backend.storage.job_publication import JobPublication
from fitcheck_backend.api.errors import ErrorBody

pytestmark=pytest.mark.integration


def prepare(fixture):
    a,c,r,_,_=fixture;c.app.state.settings.jobs_enabled=True
    value,_=guest(c)
    headers={'Origin':WEB,'X-CSRF-Token':value['csrfToken'],'Idempotency-Key':'demo'}
    body={'mode':'guest','profile':DATA['profile'],'vacancy':DATA['vacancy'],'locale':'en'}
    return a,c,r,headers,body


def test_guest_demo_replay_has_one_reservation(profile_http):
    a,c,r,h,body=prepare(profile_http)
    first=c.post('/v1/analysis-jobs',json=body,headers=h)
    assert first.status_code==202,first.text
    assert c.post('/v1/analysis-jobs',json=body,headers=h).json()==first.json()
    assert c.post('/v1/analysis-jobs',json={**body,'locale':'ru'},headers=h).status_code==409
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(QuotaReservation))==1
        frozen=s.get(Job,UUID(first.json()['jobId'])).input
        assert frozen['envelopeVersion']==2 and frozen['mode']=='guest'
        assert frozen['profile']==DATA['profile'] and frozen['memory']==[]
    q=c.get('/v1/quota?mode=guest').json()
    assert q['operations']['analysis']==dict(limit=1,remaining=0,reserved=1,consumed=0)


def test_terminal_error_returns_demo_once(profile_http):
    a,c,r,h,body=prepare(profile_http)
    result=c.post('/v1/analysis-jobs',json=body,headers=h)
    assert result.status_code==202,result.text
    queue=JobQueue(a.engine);lease=queue.claim();pub=JobPublication(a.engine)
    error=ErrorBody(code='service_unavailable',message='Unavailable',requestId='test',details=[])
    assert pub.fail(lease,error)
    assert not pub.fail(lease,error)
    q=c.get('/v1/quota?mode=guest').json()['operations']['analysis']
    assert q==dict(limit=1,remaining=1,reserved=0,consumed=0)
    assert c.post('/v1/analysis-jobs',json=body,headers={**h,'Idempotency-Key':'retry'}).status_code==202


def test_guest_suggestions_have_independent_success_quota(profile_http):
    a,c,r,h,body=prepare(profile_http)
    for i in range(5):
        result=c.post('/v1/skill-suggestion-jobs?mode=guest',json={'specialization':'React','locale':'en'},headers={**h,'Idempotency-Key':str(i)})
        assert result.status_code==202,result.text
        assert JobPublication(a.engine).succeed_suggestions(JobQueue(a.engine).claim(),['React'])
    assert c.get('/v1/quota?mode=guest').json()['operations']['suggestions']['consumed']==5
    assert c.get('/v1/quota?mode=guest').json()['remaining']==1


def test_guest_success_consumes_one_demo(profile_http):
    from fitcheck_backend.analysis.service import AnalysisResult
    from fitcheck_backend.contracts.domain import FitAnalysis
    from fitcheck_backend.contracts.resources import AnalysisSnapshot
    from fitcheck_backend.jobs.envelope import decode_envelope
    a,c,r,h,body=prepare(profile_http)
    first=c.post('/v1/analysis-jobs',json=body,headers=h);assert first.status_code==202,first.text
    lease=JobQueue(a.engine).claim();e=decode_envelope('analysis',lease.input)
    snapshot=AnalysisSnapshot(profileRevision=e.profile_revision,profile=e.profile,vacancy=e.vacancy,locale=e.locale,
        promptVersion=e.versions.prompt_version,schemaVersion=e.versions.schema_version,policyVersion=e.versions.policy_version)
    identifier=JobPublication(a.engine).succeed_analysis(lease,AnalysisResult(FitAnalysis.model_validate(DATA['analysis']),snapshot))
    assert identifier
    q=c.get('/v1/quota?mode=guest').json();assert q['remaining']==0 and q['registrationRequired']
    assert q['operations']['analysis']['consumed']==1
    assert c.get('/v1/analyses/'+str(identifier)+'?mode=guest').status_code==200
    denied=c.post('/v1/analysis-jobs',json=body,headers={**h,'Idempotency-Key':'second'})
    assert denied.status_code==429 and denied.json()['error']['code']=='quota_exceeded'
    assert c.post('/v1/analysis-jobs',json=body,headers=h).json()['jobId']==first.json()['jobId']


def test_guest_concurrent_admission_and_active_cap(profile_http):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fitcheck_backend.contracts.resources import GuestAnalysisStart,SkillSuggestionStart
    from fitcheck_backend.jobs.errors import JobError
    a,c,r,h,body=prepare(profile_http)
    from fitcheck_backend.guests.sessions import guest_cookie_name
    identity=c.app.state.auth_runtime.guests.resolve(c.cookies.get(guest_cookie_name(c.app.state.settings)))
    service=c.app.state.auth_runtime.jobs;barrier=Barrier(2)
    def start():
        barrier.wait(timeout=10)
        return service.start_analysis(identity=identity,request=GuestAnalysisStart.model_validate(body),idempotency_key='same',client_ip='127.0.0.1')
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:start(),range(2)))
    assert results[0].job_id==results[1].job_id
    with pytest.raises(JobError):service.start_suggestions(identity=identity,request=SkillSuggestionStart(specialization='React',locale='en'),idempotency_key='other',client_ip='127.0.0.1')
