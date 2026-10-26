import json
import logging
from types import SimpleNamespace
from fastapi.testclient import TestClient
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.logging import JsonFormatter
from fitcheck_backend.config import Settings
from fitcheck_backend.operations.monitoring import Counters


def test_json_logs_discard_arbitrary_messages_exceptions_and_fields():
    record = logging.LogRecord('fitcheck',logging.ERROR,'',0,'password=%s',('private',),None)
    record.exception = 'token-secret'
    record.profile = {'private':'profile'}
    record.owner_ref = 'account@email.test'
    value = json.loads(JsonFormatter().format(record))
    assert value['event']=='application_log'
    assert set(value)=={'timestamp','level','event'}


def test_metrics_token_is_required_and_route_is_not_public_contract():
    app = create_app(Settings(ops_token='a'*32))
    with TestClient(app) as client:
        for headers in [{},{'Authorization':'Bearer wrong'},{'Authorization':'Bearer '+ 'ю'*32}]:
            # httpx disallows non-ASCII outgoing headers; test byte input instead.
            if 'ю' in headers.get('Authorization',''): headers={'Authorization':b'Bearer \xff'}
            response=client.get('/internal/operations/metrics',headers=headers)
            assert response.status_code==404
        assert client.get('/internal/operations/metrics',headers={'Authorization':'Bearer '+'a'*32}).status_code==200
        assert '/internal/operations/metrics' not in client.get('/openapi.json').json()['paths']


def test_denials_are_low_cardinality_counters():
    counters=Counters()
    counters.observe('POST',429,.2,'quota_exceeded')
    counters.observe('GET',200,.1,'private-content')
    output=counters.render()
    assert 'fitcheck_admission_denials_total{reason="quota_exceeded"} 1' in output
    assert 'fitcheck_http_requests_total{method="POST",status="429"} 1' in output
    assert 'private-content' not in output

def test_collector_status_counters_are_separate_and_bounded():
    counters = Counters()
    counters.observe('POST', 401, .1, route='/internal/metrics/events')
    counters.observe('POST', 503, .1, route='/v1/jobs')
    counters.observe('DELETE', 200, .1, route='/internal/metrics/visitors/{visitorId}')
    value = counters.render()
    assert 'fitcheck_metrics_collector_requests_total{operation="events",status="401"} 1' in value
    assert 'fitcheck_metrics_collector_requests_total{operation="delete",status="200"} 1' in value
    assert 'operation="events",status="503"' not in value


def test_metrics_configuration_survives_database_unavailability():
    app = create_app(Settings(ops_token='a'*32))
    with TestClient(app) as client:
        response = client.get('/internal/operations/metrics', headers={'Authorization':'Bearer '+'a'*32})
        assert response.status_code == 200
        assert 'fitcheck_metrics_enabled 0' in response.text
        assert 'fitcheck_metrics_collector_configured 0' in response.text
        assert 'fitcheck_metrics_lifecycle_configured 0' in response.text
        assert 'fitcheck_metrics_database_scope_configured 0' in response.text

def test_collector_body_rejection_is_counted_before_routing():
    app = create_app(Settings(ops_token='a'*32))
    with TestClient(app) as client:
        assert client.post('/internal/metrics/events',content='x'*32769).status_code == 413
        assert 'fitcheck_metrics_collector_requests_total{operation="events",status="413"} 1' in app.state.ops_counters.render()

def test_lifecycle_readiness_is_independent_of_bridge_key():
    from fitcheck_backend.operations.monitoring import collection_configuration
    settings = Settings(metrics_enabled=True, metrics_environment='development', database_url='postgresql://example/db')
    result = collection_configuration(settings)
    assert 'fitcheck_metrics_enabled 1' in result
    assert 'fitcheck_metrics_lifecycle_configured 1' in result
    assert 'fitcheck_metrics_collector_configured 0' in result
    assert 'fitcheck_metrics_database_scope_configured 0' in result

def test_scrape_keeps_configuration_when_database_query_fails(monkeypatch):
    from fitcheck_backend.operations import monitoring
    settings = Settings(ops_token='a'*32, metrics_enabled=True, metrics_environment='development',
                        metrics_ingest_key='private-key', database_url='postgresql://example/db')
    def unavailable(*args, **kwargs):
        raise RuntimeError('private database error')
    monkeypatch.setattr(monitoring, 'database_metrics', unavailable)
    collector = SimpleNamespace(engine=object())
    with TestClient(create_app(settings, metrics_collector=collector)) as client:
        response = client.get('/internal/operations/metrics',headers={'Authorization':'Bearer '+'a'*32})
        assert response.status_code == 200
        assert 'fitcheck_database_up 0' in response.text
        assert 'fitcheck_metrics_collector_configured 1' in response.text
        assert 'private' not in response.text
        assert 'fitcheck_jobs{' not in response.text
