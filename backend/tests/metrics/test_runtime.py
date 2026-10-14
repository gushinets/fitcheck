from unittest.mock import Mock
from fastapi.testclient import TestClient
from fitcheck_backend.config import Settings
from fitcheck_backend.api.app import create_app
from fitcheck_backend.api.runtime import MetricsRuntime


def settings():
    return Settings(metrics_enabled=True, metrics_environment='development', metrics_ingest_key='secret', database_url='postgresql://localhost/fitcheck')


def test_owned_metrics_engine_closed(monkeypatch):
    engine = Mock()
    monkeypatch.setattr('fitcheck_backend.api.runtime.create_engine', lambda configuration:engine)
    with TestClient(create_app(settings())) as client:
        assert client.app.state.metrics_collector.engine is engine
        engine.dispose.assert_not_called()
    engine.dispose.assert_called_once()


def test_shared_auth_engine_closed_only_by_auth():
    auth = Mock()
    with TestClient(create_app(settings(),auth_runtime=auth)) as client:
        assert client.app.state.metrics_collector.engine is auth.engine
    auth.engine.dispose.assert_not_called()
    auth.close.assert_called_once()


def test_metrics_runtime_does_not_close_borrowed_engine():
    engine = Mock()
    MetricsRuntime(settings(),engine=engine).close()
    engine.dispose.assert_not_called()
