from typing import Annotated
from uuid import UUID
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from test_auth_http import http_auth, register, WEB
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.dependencies import verified_principal
from fitcheck_backend.auth.types import Principal
from fitcheck_backend.auth.access import load_owned
from fitcheck_backend.storage.models import Job
from fitcheck_backend.storage.database import unit_of_work

pytestmark=pytest.mark.integration


def test_http_two_accounts_cannot_select_or_read_foreign_identity(http_auth):
    a,first,runtime=http_auth
    own=register(first)
    own_token=a.mailer.messages[-1].token
    app2=create_app(first.app.state.settings,auth_runtime=runtime)
    def handler(job_id:UUID,principal:Annotated[Principal,Depends(verified_principal)]):
        with unit_of_work(a.engine) as s:
            return {'jobId':str(load_owned(s,Job,job_id,principal).id)}
    first.app.get('/test-owned/{job_id}')(handler)
    app2.get('/test-owned/{job_id}')(handler)
    with TestClient(app2,base_url='https://api.example.com') as second:
        other=register(second,'b@example.com')
        other_token=a.mailer.messages[-1].token
        h1={'Origin':WEB,'X-CSRF-Token':own.json()['csrfToken']}
        h2={'Origin':WEB,'X-CSRF-Token':other.json()['csrfToken']}
        assert second.post('/v1/auth/verify-email',headers=h2,json={'token':own_token}).status_code==400
        assert first.post('/v1/auth/verify-email',headers=h1,json={'token':own_token}).status_code==204
        assert second.post('/v1/auth/verify-email',headers=h2,json={'token':other_token}).status_code==204
        principal=runtime.auth.resolve(second.cookies.get('__Host-fitcheck_session'),'web')
        with unit_of_work(a.engine) as s:
            job=Job(owner_id=principal.owner_id,type='analysis',input={},idempotency_key='test',request_hash='a'*64,status='queued')
            s.add(job);s.flush();job_id=job.id
        assert second.get(f'/test-owned/{job_id}').status_code==200
        assert first.get(f'/test-owned/{job_id}').status_code==404
        assert first.get('/v1/me',params={'userId':other.json()['user']['id']}).json()['id']==own.json()['user']['id']
