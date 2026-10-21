from uuid import uuid4,UUID
import pytest
from sqlalchemy import select,func
from test_profile_http import profile_http,save,DATA
from fitcheck_backend.storage.models import Job,ProviderCall,User
from fitcheck_backend.storage.database import unit_of_work

pytestmark = pytest.mark.integration


def enabled(fixture):
    a,c,runtime,issued,headers = fixture
    c.app.state.settings.jobs_enabled = True
    save(c,headers)
    return a,c,runtime,issued,{**headers,'Idempotency-Key':'one'}


def body(): return dict(mode='account',vacancy=DATA['vacancy'],profileRevision='1',locale='en')


def test_admission_returns_202_reference_and_status(profile_http):
    a,c,r,issued,h = enabled(profile_http)
    response = c.post('/v1/analysis-jobs',json=body(),headers=h)
    assert response.status_code == 202,response.text
    assert response.json()['status'] == 'queued' and response.json()['type'] == 'analysis'
    assert c.get('/v1/jobs/'+response.json()['jobId']).json() == response.json()
    with unit_of_work(a.engine) as s: assert s.scalar(select(func.count()).select_from(ProviderCall)) == 0


def test_duplicate_returns_terminal_status(profile_http):
    from fitcheck_backend.storage.job_queue import JobQueue
    from fitcheck_backend.storage.job_publication import JobPublication
    a,c,r,issued,h = enabled(profile_http)
    request = dict(specialization='React',locale='en')
    first = c.post('/v1/skill-suggestion-jobs',json=request,headers=h)
    assert first.status_code == 202
    lease = JobQueue(a.engine).claim()
    assert JobPublication(a.engine).succeed_suggestions(lease,['React'])
    replay = c.post('/v1/skill-suggestion-jobs',json=request,headers=h)
    assert replay.status_code == 202 and replay.json()['status'] == 'succeeded'
    assert replay.json()['jobId'] == first.json()['jobId']
    assert c.get('/v1/jobs/'+replay.json()['jobId']).json()['skills'] == ['React']


@pytest.mark.parametrize('keys',[[],['one','two'],[''],['x'*201]])
def test_invalid_or_duplicate_idempotency_headers_rejected(profile_http,keys):
    a,c,r,issued,h = enabled(profile_http)
    headers = [(k,v) for k,v in h.items() if k != 'Idempotency-Key'] + [('Idempotency-Key',k) for k in keys]
    assert c.post('/v1/analysis-jobs',json=body(),headers=headers).status_code == 400
    with unit_of_work(a.engine) as s: assert s.scalar(select(func.count()).select_from(Job)) == 0


def test_guest_and_unverified_account_rejected(profile_http):
    a,c,r,issued,h = enabled(profile_http)
    with unit_of_work(a.engine) as s: s.get(User,issued.principal.user_id).email_verified_at = None
    assert c.post('/v1/analysis-jobs',json=body(),headers=h).status_code == 403
    c.cookies.clear()
    assert c.post('/v1/analysis-jobs',json=dict(mode='guest',vacancy=DATA['vacancy'],profile=DATA['profile'],locale='en'),headers=h).status_code == 401


def test_csrf_required(profile_http):
    a,c,r,issued,h = enabled(profile_http)
    h.pop('X-CSRF-Token')
    assert c.post('/v1/analysis-jobs',json=body(),headers=h).status_code == 403


def test_foreign_and_malformed_job_ids_do_not_leak(profile_http):
    a,c,r,issued,h = enabled(profile_http)
    assert c.get('/v1/jobs/'+str(uuid4())).status_code == 404
    assert c.get('/v1/jobs/not-a-uuid').status_code == 400
    with unit_of_work(a.engine) as s: assert s.scalar(select(func.count()).select_from(ProviderCall)) == 0


def test_disabled_admission_preserves_existing_get(profile_http):
    a,c,r,issued,h = enabled(profile_http)
    response = c.post('/v1/analysis-jobs',json=body(),headers=h)
    assert response.status_code == 202
    c.app.state.settings.jobs_enabled = False
    assert c.post('/v1/analysis-jobs',json=body(),headers={**h,'Idempotency-Key':'two'}).status_code == 503
    assert c.get('/v1/jobs/'+response.json()['jobId']).status_code == 200


def test_api_admits_openai_versions_without_provider_key(profile_http):
    a,c,r,issued,h = enabled(profile_http)
    assert c.app.state.settings.open_ai_key is None
    response = c.post('/v1/analysis-jobs',json=body(),headers=h)
    assert response.status_code == 202
    with unit_of_work(a.engine) as s:
        versions = s.get(Job, UUID(response.json()['jobId'])).input['versions']
        assert versions['provider'] == 'openai'
        assert versions['model'] == 'gpt-6-luna'
        assert versions['policyVersion'] == 'fitcheck.llm.policy.v2'


def test_job_get_contains_committed_result(profile_http):
    from fitcheck_backend.storage.job_queue import JobQueue
    from fitcheck_backend.storage.job_publication import JobPublication
    from fitcheck_backend.contracts.domain import FitAnalysis
    from fitcheck_backend.contracts.resources import AnalysisSnapshot
    from fitcheck_backend.analysis.service import AnalysisResult
    a,c,r,issued,h = enabled(profile_http)
    response = c.post('/v1/analysis-jobs',json=body(),headers=h)
    assert response.status_code == 202
    lease = JobQueue(a.engine).claim()
    snapshot = AnalysisSnapshot(profileRevision='1',profile=DATA['profile'],vacancy=DATA['vacancy'],locale='en',
        promptVersion='fitcheck.analysis.prompt.v2',schemaVersion='fitcheck.analysis.v1',policyVersion='fitcheck.llm.policy.v2')
    analysis_id = JobPublication(a.engine).succeed_analysis(lease,AnalysisResult(FitAnalysis.model_validate(DATA['analysis']),snapshot))
    result = c.get('/v1/jobs/'+response.json()['jobId'])
    assert result.status_code == 200 and result.json()['analysisId'] == str(analysis_id)
    assert result.json()['result']['snapshot']['profileRevision'] == '1'
