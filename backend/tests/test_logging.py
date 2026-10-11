import io
import logging
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
    assert 'method=GET path=/health/live status=200' in output
    assert 'method=GET path=/crash status=500' in output
    assert 'method=POST path=/missing status=404' in output
    assert not any(secret in output for secret in ['query-secret','auth-secret','body-secret','exception-secret'])
    # The configured stream is test-owned; release handlers before it is closed.
    for handler in list(logging.getLogger('fitcheck').handlers):
        logging.getLogger('fitcheck').removeHandler(handler)
        handler.close()
