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
        assert client.get('/internal/operations/metrics',headers={'Authorization':'Bearer '+'a'*32}).status_code==503
        assert '/internal/operations/metrics' not in client.get('/openapi.json').json()['paths']


def test_denials_are_low_cardinality_counters():
    counters=Counters()
    counters.observe('POST',429,.2,'quota_exceeded')
    counters.observe('GET',200,.1,'private-content')
    output=counters.render()
    assert 'fitcheck_admission_denials_total{reason="quota_exceeded"} 1' in output
    assert 'fitcheck_http_requests_total{method="POST",status="429"} 1' in output
    assert 'private-content' not in output
