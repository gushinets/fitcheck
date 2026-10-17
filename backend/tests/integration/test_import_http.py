from uuid import uuid4
import pytest
from sqlalchemy import select,func
from test_profile_http import profile_http,WEB
from test_import_repository import raw_row
from fitcheck_backend.storage.database import unit_of_work
from fitcheck_backend.storage.models import Job,ProviderCall,QuotaReservation,User
pytestmark=pytest.mark.integration


def payload(**changes):return dict(version=1,source='website_indexeddb_v1',sourceUserId='alice',history=[raw_row()])|changes


def test_import_auth_idempotency_and_capacity(profile_http):
    a,c,r,issued,h=profile_http
    c.app.state.settings.jobs_enabled=True
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
    def send(_):return c.post('/v1/import-jobs',headers=h|{'Idempotency-Key':'race'},json=payload())
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(send,range(2)))
    assert [v.status_code for v in results]==[202,202]
    assert results[0].json()==results[1].json()
    identifier=results[0].json()['importId']
    other=a.service.register('other-import@example.com','correct horse battery','127.0.0.2')
    with unit_of_work(a.engine) as s:s.get(User,other.principal.user_id).email_verified_at=a.clock()
    c.cookies.clear();c.cookies.set('__Host-fitcheck_session',other.token)
    assert c.get('/v1/import-jobs/'+identifier).status_code==404
