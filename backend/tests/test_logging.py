import io
import logging
import json
from fastapi.testclient import TestClient
from fitcheck_backend import __main__ as cli


def test_cli_logs_request_ids_without_sensitive_data(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr('sys.stderr', stream)
    request_ids = []
    def serve(app, **kwargs):
        assert kwargs['access_log'] is False
        @app.get('/crash')
        async def crash():
            raise RuntimeError('exception-secret')
        client = TestClient(app, raise_server_exceptions=False)
        for path in ['/health/live?token=query-secret', '/crash']:
            response = client.get(path, headers={'Authorization':'Bearer auth-secret'})
            request_ids.append(response.headers['X-Request-ID'])
        client.post('/missing', json={'password':'body-secret'})
    monkeypatch.setattr(cli.uvicorn, 'run', serve)
    cli.main()
    output = stream.getvalue()
    assert all(request_id in output for request_id in request_ids)
    entries = [json.loads(line) for line in output.splitlines()]
    assert [(row['method'],row['route'],row['status']) for row in entries] == [
        ('GET','/health/live',200),('GET','/crash',500),('POST','/unmatched',404)]
    assert all(row['event']=='http_request' and row['duration_ms']>=0 for row in entries)
    assert not any(secret in output for secret in ['query-secret','auth-secret','body-secret','exception-secret'])
    # The configured stream is test-owned; release handlers before it is closed.
    for name in ('fitcheck','uvicorn.error'):
        for handler in list(logging.getLogger(name).handlers):
            logging.getLogger(name).removeHandler(handler)
            handler.close()
