from fastapi.testclient import TestClient
from fitcheck_backend.api.app import create_app
from fitcheck_backend.config import Settings


def test_disabled_auth_routes_are_safe_503_without_database():
    with TestClient(create_app(Settings())) as client:
        for method,path in [('get','/v1/auth/csrf'),('get','/v1/auth/session'),('get','/v1/me'),('post','/v1/auth/register'),('post','/v1/auth/login'),('post','/v1/auth/logout'),('post','/v1/auth/verify-email'),('post','/v1/auth/verify-email/request'),('post','/v1/auth/password-reset/request'),('post','/v1/auth/password-reset/confirm'),('post','/v1/auth/extension/authorize'),('post','/v1/auth/extension/token'),('post','/v1/auth/extension/revoke'),('delete','/v1/me')]:
            r=client.request(method,path)
            assert r.status_code==503 and r.json()['error']['code']=='service_unavailable'
            assert r.headers['cache-control']=='no-store'
        assert client.get('/health/ready').json()=={'status':'ok','stage':'foundation'}
