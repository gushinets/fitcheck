import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.runtime import AuthRuntime
from fitcheck_backend.auth.crypto import b64
from fitcheck_backend.config import Settings

pytestmark=pytest.mark.integration
WEB='https://web.example.com'
EXT='chrome-extension://'+'a'*32
REDIRECT='https://'+'a'*32+'.chromiumapp.org/callback'
PASSWORD='correct horse battery'


@pytest.fixture
def http_auth(auth_components):
    a=auth_components
    s=Settings(env='production',auth_enabled=True,auth_secret='78'*32,auth_web_base_url=WEB,
        database_url=a.engine.url.render_as_string(hide_password=False),allowed_origins=[WEB,EXT],auth_extension_redirect_uris=[REDIRECT])
    runtime=AuthRuntime(s,engine=a.engine,mailer=a.mailer,clock=a.clock)
    with TestClient(create_app(s,auth_runtime=runtime),base_url='https://api.example.com') as c:
        yield a,c,runtime


def register(c,email='a@example.com'):
    csrf=c.get('/v1/auth/csrf',headers={'Origin':WEB}).json()['csrfToken']
    return c.post('/v1/auth/register',headers={'Origin':WEB,'X-CSRF-Token':csrf},json={'email':email,'password':PASSWORD})


def test_http_bootstrap_login_cookie_and_session_recovery(http_auth):
    a,c,runtime=http_auth
    result=register(c)
    assert result.status_code==201,result.text
    cookie=result.headers['set-cookie']
    assert '__Host-fitcheck_session=' in cookie and 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Domain=' not in cookie
    assert result.headers['cache-control']=='no-store'
    assert set(result.json())=={'user','csrfToken'}
    assert not result.json()['user']['emailVerified']
    recovered=c.get('/v1/auth/session')
    assert recovered.status_code==200 and recovered.json()==result.json()
    assert c.get('/v1/me').json()==result.json()['user']
    csrf=c.get('/v1/auth/csrf',headers={'Origin':WEB}).json()['csrfToken']
    logged=c.post('/v1/auth/login',json={'email':'a@example.com','password':PASSWORD},headers={'Origin':WEB,'X-CSRF-Token':csrf})
    assert logged.status_code==200 and logged.json()['csrfToken']!=result.json()['csrfToken']


def test_http_origin_csrf_duplicate_headers_and_mixed_credentials(http_auth):
    a,c,runtime=http_auth
    result=register(c)
    session_csrf=result.json()['csrfToken']
    for headers in [{},{'Origin':'null'},{'Origin':'https://evil.example.com'},{'Origin':WEB,'X-CSRF-Token':'wrong'}]:
        assert c.post('/v1/auth/logout',headers=headers).status_code==403
    assert c.post('/v1/auth/logout',headers=[('Origin',WEB),('Origin',WEB),('X-CSRF-Token',session_csrf)]).status_code==403
    assert c.get('/v1/me',headers={'Authorization':'Bearer '+'a'*43}).status_code==403
    assert c.post('/v1/auth/logout',headers={'Origin':WEB,'X-CSRF-Token':session_csrf}).status_code==204
    assert c.get('/v1/me').status_code==401


def test_http_pending_verified_extension_and_deletion(http_auth):
    a,c,runtime=http_auth
    result=register(c)
    h={'Origin':WEB,'X-CSRF-Token':result.json()['csrfToken']}
    challenge=b64(hashlib.sha256(('v'*43).encode()).digest())
    body={'redirectUri':REDIRECT,'codeChallenge':challenge,'codeChallengeMethod':'S256','state':'state'}
    assert c.post('/v1/auth/extension/authorize',headers=h,json=body).status_code==403
    assert c.get('/v1/auth/verify-email',params={'token':a.mailer.messages[-1].token}).status_code==405
    assert c.post('/v1/auth/verify-email',headers=h,json={'token':a.mailer.messages[-1].token}).status_code==204
    assert c.get('/v1/me').json()['emailVerified']
    code=c.post('/v1/auth/extension/authorize',headers=h,json=body).json()['code']
    web_cookie=c.cookies.get('__Host-fitcheck_session')
    c.cookies.clear()
    issued=c.post('/v1/auth/extension/token',headers={'Origin':EXT},json={'code':code,'codeVerifier':'v'*43,'redirectUri':REDIRECT})
    assert issued.status_code==200,issued.text
    bearer={'Authorization':'Bearer '+issued.json()['accessToken'],'Origin':EXT}
    assert c.get('/v1/me',headers=bearer).status_code==200
    assert c.post('/v1/auth/logout',headers=bearer).status_code in {401,403}
    assert c.post('/v1/auth/extension/revoke',headers=bearer).status_code==204
    assert c.get('/v1/me',headers=bearer).status_code==401
    c.cookies.set('__Host-fitcheck_session',web_cookie,domain='api.example.com',path='/')
    assert c.request('DELETE','/v1/me',headers=h,json={'password':'wrong'}).status_code==401
    assert c.request('DELETE','/v1/me',headers=h,json={'password':PASSWORD,'ownerId':'forged'}).status_code==400
    assert c.request('DELETE','/v1/me',headers=h,json={'password':PASSWORD}).status_code==204
    assert c.get('/v1/me').status_code==401


def test_auth_readiness_requires_db_and_schema_head(http_auth):
    a,c,runtime=http_auth
    ready=c.get('/health/ready')
    assert ready.status_code==200 and ready.json()['stage']=='auth_storage'
    assert ready.json()['dependencies']['email']=='configured'
    with a.engine.begin() as conn:conn.execute(text("UPDATE alembic_version SET version_num='0002'"))
    try:
        assert c.get('/health/ready').status_code==503
        assert c.get('/health/live').status_code==200
    finally:
        with a.engine.begin() as conn:conn.execute(text("UPDATE alembic_version SET version_num='0003'"))
    a.mailer.enabled=False
    ready=c.get('/health/ready')
    assert ready.status_code==200 and ready.json()['dependencies']['email']=='unconfigured'


def test_http_missing_mail_returns_503_without_registration(http_auth):
    a,c,runtime=http_auth
    a.mailer.enabled=False
    assert register(c).status_code==503
    for email in ['a@example.com','missing@example.com']:
        for path in ['/v1/auth/verify-email/request','/v1/auth/password-reset/request']:
            r=c.post(path,headers={'Origin':WEB},json={'email':email})
            assert r.status_code==503 and r.json()['error']['code']=='email_unavailable'


def test_http_reset_flow_revokes_cookie(http_auth):
    a,c,runtime=http_auth
    issued=register(c)
    h={'Origin':WEB,'X-CSRF-Token':issued.json()['csrfToken']}
    assert c.post('/v1/auth/verify-email/request',headers={'Origin':WEB},json={'email':'a@example.com'}).status_code==204
    assert c.post('/v1/auth/verify-email',headers=h,json={'token':a.mailer.messages[-1].token}).status_code==204
    assert c.post('/v1/auth/password-reset/request',headers={'Origin':WEB},json={'email':'a@example.com'}).status_code==204
    token=a.mailer.messages[-1].token
    new_password='changed password 123'
    assert c.post('/v1/auth/password-reset/confirm',headers={'Origin':WEB},json={'token':token,'password':new_password}).status_code==204
    assert c.get('/v1/me').status_code==401
    assert c.post('/v1/auth/password-reset/confirm',headers={'Origin':WEB},json={'token':token,'password':new_password}).status_code==400
    csrf=c.get('/v1/auth/csrf',headers={'Origin':WEB}).json()['csrfToken']
    assert c.post('/v1/auth/login',headers={'Origin':WEB,'X-CSRF-Token':csrf},json={'email':'a@example.com','password':new_password}).status_code==200


def test_ready_db_unavailable_does_not_fail_liveness(http_auth):
    from fitcheck_backend.storage.database import create_engine
    a,c,runtime=http_auth
    previous=runtime.engine
    bad=create_engine(Settings(database_url='postgresql://fake:private-password@127.0.0.1:1/fitcheck_test'))
    runtime.engine=bad
    try:
        result=c.get('/health/ready')
        assert result.status_code==503 and 'private-password' not in result.text
        assert c.get('/health/live').status_code==200
    finally:
        runtime.engine=previous
        bad.dispose()
