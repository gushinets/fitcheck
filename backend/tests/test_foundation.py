import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from fitcheck_backend.config import Settings
from fitcheck_backend.api.app import create_app


def test_health_without_database_or_provider_secrets(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPEN_AI_KEY", raising=False)
    with TestClient(create_app(Settings())) as client:
        for path in ["/health/live", "/health/ready"]:
            response = client.get(path)
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "stage": "foundation"}


@pytest.mark.parametrize("values", [
    {"port": 0}, {"port": 65536}, {"api_body_max_bytes": 0},
    {"api_body_max_bytes": 16_777_217}, {"env": "prod"}, {"log_level": "verbose"},
    {"allowed_origins": ["*"]}, {"allowed_origins": ["https://*.example.com"]},
    {"allowed_origins": ["https://example.com/path"]},
    {"allowed_origins": ["https://user:pass@example.com"]},
])
def test_invalid_settings(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_defaults():
    settings = Settings()
    assert (settings.env, settings.host, settings.port, settings.log_level) == ("dev", "127.0.0.1", 8000, "info")
    assert settings.api_body_max_bytes == 1_048_576
    assert settings.allowed_origins == []


def test_explicit_settings_override_environment(monkeypatch):
    monkeypatch.setenv("FITCHECK_PORT", "65536")
    app = create_app(Settings(port=9000))
    assert app.state.settings.port == 9000


def test_origin_environment_json(monkeypatch):
    monkeypatch.setenv("FITCHECK_ALLOWED_ORIGINS", '["https://fitcheck.example","http://localhost:3000"]')
    assert Settings().allowed_origins == ["https://fitcheck.example", "http://localhost:3000"]
