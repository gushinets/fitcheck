import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fitcheck_backend.api.app import create_app
from fitcheck_backend.config import Settings
from fitcheck_backend.contracts.openapi import export_openapi


def test_removed_login_routes_are_absent_from_runtime_and_contract():
    app = create_app(Settings())
    doc = export_openapi(app)
    with TestClient(app) as client:
        for action in ['authorize', 'token', 'revoke']:
            path = '/v1/auth/extension/' + action
            assert client.post(path, json={}).status_code == 404
            assert path not in doc['paths']
    assert set(doc['components']['securitySchemes']) == {'webSession', 'guestSession', 'metricsBridge'}
    assert doc['paths']['/v1/profile']['put']['security'] == [{'webSession': []}]
    assert not any(name.startswith('Extension') for name in doc['components']['schemas'])


def test_only_website_origins_are_configurable():
    assert Settings(allowed_origins=['https://site.example.com']).allowed_origins == ['https://site.example.com']
    with pytest.raises(ValidationError):
        Settings(allowed_origins=['chrome-extension://' + 'a' * 32])
