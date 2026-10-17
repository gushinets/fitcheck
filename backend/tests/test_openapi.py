import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from fitcheck_backend.api.app import create_app
from fitcheck_backend.config import Settings
from fitcheck_backend.contracts.openapi import export_openapi

EXPECTED = {
    '/v1/auth/register': {'post'}, '/v1/auth/login': {'post'}, '/v1/auth/logout': {'post'},
    '/v1/auth/verify-email': {'post'}, '/v1/auth/password-reset/request': {'post'}, '/v1/auth/password-reset/confirm': {'post'},
    '/v1/me': {'get','delete'},
    '/v1/profile': {'get','put'}, '/v1/preferences': {'get','put'}, '/v1/draft': {'get','put','delete'},
    '/v1/profile/revisions/{revision}': {'get'}, '/v1/profile/revisions/{revision}/comparison': {'get'},
    '/v1/extractions': {'post'}, '/v1/skill-suggestion-jobs': {'post'}, '/v1/analysis-jobs': {'post'}, '/v1/jobs/{jobId}': {'get'},
    '/v1/analyses/{analysisId}': {'get'}, '/v1/history': {'get','delete'}, '/v1/analyses/{analysisId}/feedback': {'put'},
    '/v1/analyses/{analysisId}/application-status': {'put'}, '/v1/analyses/{analysisId}/reanalyses': {'post'},
    '/v1/guest-sessions': {'post'}, '/v1/quota': {'get'}, '/v1/guest-claims': {'post'}, '/v1/import-jobs': {'post'}, '/v1/import-jobs/{importId}': {'get'},
}


def test_complete_valid_contract_and_live_route_separation():
    app = create_app(Settings())
    document = export_openapi(app)
    validate(document)
    ids = []
    for path, methods in EXPECTED.items():
        assert set(document['paths'][path]) == methods
        for method in methods:
            operation = document['paths'][path][method]
            implemented = method in app.openapi()['paths'].get(path,{})
            assert operation['x-fitcheck-implementation'] == ('implemented' if implemented else 'planned')
            assert operation['x-fitcheck-owner-task'].startswith('ANY-')
            ids.append(operation['operationId'])
            for status in ['400','401','403','404','409','413','415','429','500','502','503','504']:
                assert operation['responses'][status]['content']['application/json']['schema']['$ref'].endswith('/ErrorEnvelope')
            response = getattr(TestClient(app), method)(path.replace('{jobId}', 'j').replace('{analysisId}', 'a').replace('{importId}', 'i'))
            assert response.status_code == (503 if implemented else 404)
    assert len(ids) == len(set(ids))
    assert set(app.openapi()['paths']) == {'/health/live','/health/ready', '/internal/metrics/events', '/internal/metrics/attempts', '/internal/metrics/visitors/{visitorId}'} | {p for p, methods in document['paths'].items() if any(m['x-fitcheck-implementation']=='implemented' for m in methods.values())}
    for path in ['/health/live','/health/ready']:
        assert document['paths'][path]['get']['x-fitcheck-implementation'] == 'implemented'
        assert document['paths'][path]['get']['responses'] == app.openapi()['paths'][path]['get']['responses']
    assert document['components']['schemas']['HealthResponse'] == app.openapi()['components']['schemas']['HealthResponse']


def test_security_idempotency_and_pagination():
    document = export_openapi(create_app(Settings()))
    profile = document['paths']['/v1/profile']['put']
    assert profile['security'] == [{'webSession': []}]
    assert profile['x-fitcheck-cookie-mutation'] == {'originRequired': True, 'csrfHeader': 'X-CSRF-Token'}
    extraction = document['paths']['/v1/extractions']['post']
    assert extraction['security'] == [{'webSession': []}, {'guestSession': []}]
    assert extraction['x-fitcheck-cookie-mutation'] == profile['x-fitcheck-cookie-mutation']
    claim = document['paths']['/v1/guest-claims']['post']
    assert claim['security'] == [{'webSession': [], 'guestSession': []}]
    for path in ['/v1/analysis-jobs','/v1/skill-suggestion-jobs','/v1/import-jobs','/v1/guest-claims','/v1/analyses/{analysisId}/reanalyses']:
        assert any(p['name'] == 'Idempotency-Key' and p['required'] for p in document['paths'][path]['post']['parameters'])
    history = document['paths']['/v1/history']['get']
    params = {p['name']: p for p in history['parameters']}
    assert params['limit']['schema']['minimum'] == 1
    assert params['limit']['schema']['maximum'] == 100
    assert params['verdict']['schema']['enum'] == ['GO','NO_GO']
    assert 'desiredMonthlyIncome' not in document['components']['schemas']['FreelancerProfile']['properties']
    assert document['components']['schemas']['FreelancerProfile']['properties']['rateCurrency']['enum'] == ['USD','EUR','RUB']


def test_export_is_deterministic_and_config_independent(monkeypatch):
    document = export_openapi(create_app(Settings()))
    monkeypatch.setenv('FITCHECK_PORT', 'invalid')
    monkeypatch.setenv('OPEN_AI_KEY','secret-should-not-appear')
    assert export_openapi(create_app(Settings(port=8000))) == document
    assert 'secret-should-not-appear' not in json.dumps(document)


def test_export_cli_detects_drift_without_rewriting(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    output = tmp_path / 'contract.json'
    env = {**os.environ, 'PYTHONPATH': str(backend / 'src'), 'FITCHECK_PORT':'invalid'}
    command = [sys.executable, str(backend / 'scripts/export_openapi.py'), '--output', str(output)]
    first = subprocess.run(command, env=env, capture_output=True)
    assert first.returncode == 0, first.stderr.decode()
    original = output.read_bytes()
    assert subprocess.run(command+['--check'],env=env,capture_output=True).returncode == 0
    output.write_text('{}\n')
    assert subprocess.run(command+['--check'],env=env,capture_output=True).returncode == 1
    assert output.read_text() == '{}\n'
    assert original.endswith(b'\n')


def test_existing_legacy_error_codes_have_http_semantics():
    mapping = export_openapi(create_app(Settings()))['x-fitcheck-legacy-error-status']
    assert mapping == {'rate_limit':429, 'timeout':504, 'invalid_output':502, 'upstream':502, 'invalid_url':400, 'blocked_address':403, 'redirect_limit':502, 'unsupported_content':415, 'response_too_large':413, 'fetch_failed':502}


def test_internal_metrics_contract_has_bridge_security_only():
    document = export_openapi(create_app(Settings()))
    for path in ['/internal/metrics/events','/internal/metrics/attempts','/internal/metrics/visitors/{visitorId}']:
        for operation in document['paths'][path].values():
            assert operation['security'] == [{'metricsBridge':[]}]
            assert operation['x-fitcheck-internal'] is True
            assert 'x-fitcheck-cookie-mutation' not in operation
    assert document['components']['securitySchemes']['metricsBridge']['in'] == 'header'


def test_guest_contract_security_and_quota_errors():
    document=export_openapi(create_app(Settings()))
    paths=document['paths']
    for path,method in [('/v1/guest-sessions','post'),('/v1/guest-claims','post'),('/v1/quota','get')]:
        assert paths[path][method]['x-fitcheck-implementation']=='implemented'
    claim=paths['/v1/guest-claims']['post']
    assert claim['operationId']=='claimGuestData'
    assert claim['security']==[{'webSession':[],'guestSession':[]}]
    assert claim['x-fitcheck-cookie-mutation']['guestCsrfHeader']=='X-Guest-CSRF-Token'
    assert any(p['name']=='X-Guest-CSRF-Token' and p['required'] for p in claim['parameters'])
    assert paths['/v1/history']['get']['security']==[{'webSession':[]}]
    assert paths['/v1/import-jobs']['post']['x-fitcheck-implementation']=='planned'
    assert any(p['name']=='mode' and p['in']=='query' for p in paths['/v1/quota']['get']['parameters'])
    assert paths['/v1/analysis-jobs']['post']['security']==[{'webSession':[]},{'guestSession':[]}]
    quota=document['components']['schemas']['OperationQuota']
    assert quota['properties']['remaining']['minimum']==0
    response=paths['/v1/analysis-jobs']['post']['responses']['429']
    assert 'quota_exceeded' in response['description'] and 'budget_exceeded' in response['description']
    assert response['content']['application/json']['schema']=={'$ref':'#/components/schemas/ErrorEnvelope'}
