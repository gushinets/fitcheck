from uuid import uuid4
import pytest
from sqlalchemy import event,select,func
from sqlalchemy.exc import SQLAlchemyError
from test_profile_http import profile_http,WEB
from test_import_repository import raw_row
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job,MetricJournal,ProviderCall,QuotaReservation,User
pytestmark=pytest.mark.integration


def payload(**changes):return dict(version=1,source='website_indexeddb_v1',sourceUserId='alice',history=[raw_row()])|changes


@pytest.mark.parametrize('metrics_enabled',[False,True])
def test_import_auth_idempotency_and_capacity(profile_http,metrics_enabled):
    a,c,r,issued,h=profile_http
    c.app.state.settings.jobs_enabled=True
    r.settings.metrics_enabled=metrics_enabled
    r.settings.metrics_environment='test'
    headers=h|{'Idempotency-Key':'import'}
    first=c.post('/v1/import-jobs',headers=headers,json=payload())
    assert first.status_code==202,first.text
    identifier=first.json()['importId']
    assert c.post('/v1/import-jobs',headers=headers,json=payload()).json()==first.json()
    assert c.post('/v1/import-jobs',headers=headers,json=payload(sourceUserId='bob')).status_code==409
    assert c.get('/v1/import-jobs/'+identifier).json()['status']=='queued'
    assert c.get('/v1/import-jobs/'+str(uuid4())).status_code==404
    assert c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'two'},json=payload()).status_code==202
    assert c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'three'},json=payload()).status_code==429
    for bad in [{'Origin':WEB,'Idempotency-Key':'bad'},{'X-CSRF-Token':h['X-CSRF-Token'],'Idempotency-Key':'bad'}]:
        assert c.post('/v1/import-jobs',headers=bad,json=payload()).status_code==403
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(Job))==2
        assert s.scalar(select(func.count()).select_from(ProviderCall))==0
        assert s.scalar(select(func.count()).select_from(QuotaReservation))==0
        events=list(s.scalars(select(MetricJournal).where(MetricJournal.name=='job_admitted')))
        assert len(events)==(2 if metrics_enabled else 0)
        jobs={f'job:{job.id}:admitted':job for job in s.scalars(select(Job))}
        for value in events:
            job=jobs[value.domain_key]
            assert value.source=='backend_server' and value.environment=='test'
            assert value.owner_id==issued.principal.owner_id
            assert value.subject_kind=='account' and value.subject_id==job.owner_id
            assert value.properties=={'jobType':'import'} and value.occurred_at==job.created_at
    c.cookies.clear()
    assert c.get('/v1/import-jobs/'+identifier).status_code==401
    assert c.post('/v1/import-jobs',headers=headers,json=payload()).status_code==401


def test_disabled_unverified_and_sanitized_invalid_data(profile_http):
    a,c,r,issued,h=profile_http
    headers=h|{'Idempotency-Key':'safe'}
    assert c.post('/v1/import-jobs',headers=headers,json=payload()).status_code==503
    c.app.state.settings.jobs_enabled=True
    with unit_of_work(a.engine) as s:s.get(User,issued.principal.user_id).email_verified_at=None
    assert c.post('/v1/import-jobs',headers=headers,json=payload()).status_code==403
    with unit_of_work(a.engine) as s:s.get(User,issued.principal.user_id).email_verified_at=a.clock()
    result=c.post('/v1/import-jobs',headers=headers,json=payload(history=[{'id':'bad','password':'DO-NOT-PERSIST'}],profile={'password':'DO-NOT-PERSIST'}))
    assert result.status_code==202,result.text
    with unit_of_work(a.engine) as s:
        job=s.scalar(select(Job));assert 'DO-NOT-PERSIST' not in str(job.input)
    assert c.post('/v1/import-jobs',headers=headers,json=payload(version=3)).status_code==400
    assert c.post('/v1/import-jobs',headers=headers,json=payload(password='DO-NOT-PERSIST')).status_code==400


def test_imports_count_against_other_jobs_and_body_ceiling(profile_http):
    from fastapi.testclient import TestClient
    from fitcheck_backend.api.app import create_app
    a,c,r,issued,h=profile_http
    c.app.state.settings.jobs_enabled=True
    for key in ['one','two']:
        assert c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':key},json=payload()).status_code==202
    assert c.post('/v1/skill-suggestion-jobs',headers=h|{'Idempotency-Key':'llm'},json={'specialization':'Developer','locale':'en'}).status_code==429
    settings=r.settings.model_copy(update={'api_body_max_bytes':16*1024*1024})
    with TestClient(create_app(settings,auth_runtime=r),base_url='https://api.example.com') as other:
        response=other.post('/v1/import-jobs',content=b' '* (5*1024*1024+1),headers={'Content-Type':'application/json'})
        assert response.status_code==413


def test_concurrent_same_key_admission_and_foreign_owner(profile_http):
    from concurrent.futures import ThreadPoolExecutor
    a,c,r,issued,h=profile_http
    c.app.state.settings.jobs_enabled=True
    r.settings.metrics_enabled=True
    r.settings.metrics_environment='test'
    def send(_):return c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'race'},json=payload())
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(send,range(2)))
    assert [v.status_code for v in results]==[202,202]
    assert results[0].json()==results[1].json()
    identifier=results[0].json()['importId']
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(Job))==1
        events=list(s.scalars(select(MetricJournal).where(MetricJournal.name=='job_admitted')))
        assert len(events)==1 and events[0].domain_key==f'job:{identifier}:admitted'
    other=a.service.register('other-import@example.com','correct horse battery','127.0.0.2')
    with unit_of_work(a.engine) as s:s.get(User,other.principal.user_id).email_verified_at=a.clock()
    c.cookies.clear();c.cookies.set('__Host-fitcheck_session',other.token)
    assert c.get('/v1/import-jobs/'+identifier).status_code==404


def test_import_and_admission_event_roll_back_together(profile_http):
    a,c,r,issued,h=profile_http
    c.app.state.settings.jobs_enabled=True
    r.settings.metrics_enabled=True
    r.settings.metrics_environment='test'
    def fail(conn,cursor,statement,params,context,many):
        if statement.startswith('INSERT INTO metric_journal'):
            raise SQLAlchemyError('forced metrics failure')
    event.listen(a.engine,'before_cursor_execute',fail)
    try:
        response=c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'rollback'},json=payload())
        assert response.status_code==503,response.text
    finally:
        event.remove(a.engine,'before_cursor_execute',fail)
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(Job))==0
        assert s.scalar(select(func.count()).select_from(MetricJournal))==0
    assert c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'rollback'},json=payload()).status_code==202
    with unit_of_work(a.engine) as s:
        assert s.scalar(select(func.count()).select_from(Job))==1
        assert s.scalar(select(func.count()).select_from(MetricJournal))==1


def test_normalized_duplicate_ids_rejected_before_job_creation(profile_http):
    a,c,r,issued,h=profile_http;c.app.state.settings.jobs_enabled=True
    response=c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'trim'},json=payload(history=[raw_row(id='row'),raw_row(id=' row ')]))
    assert response.status_code==400,response.text
    with unit_of_work(a.engine) as s:assert s.scalar(select(func.count()).select_from(Job))==0


def test_jsonb_unsafe_rows_are_isolated_and_source_identity_rejected(profile_http):
    from copy import deepcopy
    a,c,r,issued,h=profile_http;c.app.state.settings.jobs_enabled=True
    broken=raw_row(id='bad-content');broken['job']['description']='bad\x00content'
    profile=deepcopy(broken['profile']);profile['specialization']='bad\x00profile'
    response=c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'nul'},json=payload(profile=profile,history=[raw_row(),broken,raw_row(id='bad\x00id')]))
    assert response.status_code==202,response.text
    with unit_of_work(a.engine) as s:
        job=s.scalar(select(Job));assert '\x00' not in str(job.input)
        assert job.input['profile']=={}
        assert job.input['history'][1]=={'id':'bad-content','invalid':True}
        assert job.input['history'][2]=={'invalid':True}
    bad_source=c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'nul-source'},json=payload(sourceUserId='bad\x00source'))
    assert bad_source.status_code==400,bad_source.text
