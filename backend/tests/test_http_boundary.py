import asyncio
import json
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from fitcheck_backend.api.app import create_app
from fitcheck_backend.config import Settings


class Payload(BaseModel):
    count: int


@pytest.fixture
def app():
    app = create_app(Settings(allowed_origins=["https://web.example", "chrome-extension://abc"]))
    @app.post("/test-json")
    async def payload(value: Payload):
        return value.model_dump()
    @app.get("/crash")
    async def crash():
        raise RuntimeError("password=supersecret")
    return app


def envelope(response, code):
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["requestId"] == response.headers["x-request-id"]
    UUID(response.headers["x-request-id"])


def test_validation_is_400_and_redacted(app):
    response = TestClient(app).post("/test-json", json={"count": "password=supersecret"})
    assert response.status_code == 400
    envelope(response, "invalid_request")
    assert "supersecret" not in response.text
    assert response.json()["error"]["details"] == [{"location": ["body", "count"], "code": "int_parsing"}]


def test_unhandled_error_is_safe(app, caplog):
    response = TestClient(app, raise_server_exceptions=False).get("/crash", headers={"Origin": "https://web.example"})
    assert response.status_code == 500
    envelope(response, "internal_error")
    assert "supersecret" not in response.text + caplog.text
    assert response.headers["access-control-allow-origin"] == "https://web.example"


def test_404_405_share_envelope(app):
    client = TestClient(app)
    for method, path, status, code in [("get", "/missing", 404, "not_found"), ("post", "/health/live", 405, "method_not_allowed")]:
        response = getattr(client, method)(path)
        assert response.status_code == status
        envelope(response, code)
        if status == 405:
            assert "GET" in response.headers["allow"]


def test_request_id_cannot_be_spoofed(app):
    response = TestClient(app).get("/health/live", headers={"X-Request-ID": "client-spoof"})
    assert response.headers["x-request-id"] != "client-spoof"
    UUID(response.headers["x-request-id"])


@pytest.mark.parametrize("origin,allowed,credentials", [
    ("https://web.example", True, True), ("chrome-extension://abc", True, False),
    ("https://web.example.evil", False, False), ("chrome-extension://evil", False, False),
])
def test_cors_exact_origins(app, origin, allowed, credentials):
    client = TestClient(app)
    response = client.get("/health/live", headers={"Origin": origin})
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed
    assert (response.headers.get("access-control-allow-credentials") == "true") is credentials
    response = client.options("/test-json", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,authorization,x-csrf-token,idempotency-key"})
    assert response.status_code == (204 if allowed else 403)
    if allowed:
        assert response.headers["access-control-allow-origin"] == origin
    else:
        envelope(response, "forbidden")


def test_cors_rejects_unapproved_header(app):
    response = TestClient(app).options("/test-json", headers={"Origin": "https://web.example", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-arbitrary"})
    assert response.status_code == 403
    envelope(response, "forbidden")


def test_json_content_type_and_malformed_json(app):
    client = TestClient(app)
    response = client.post("/test-json", content='{"count":1}', headers={"Content-Type": "text/plain"})
    assert response.status_code == 415
    envelope(response, "unsupported_content_type")
    response = client.post("/test-json", content="{bad", headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    envelope(response, "invalid_request")


@pytest.mark.parametrize("declared", [None, "1", "9"])
def test_actual_body_limit(declared):
    app = create_app(Settings(api_body_max_bytes=8))
    @app.post("/body")
    async def body(value: dict):
        return value
    async def run(chunks):
        messages = iter({"type": "http.request", "body": b, "more_body": i < len(chunks)-1} for i, b in enumerate(chunks))
        output = []
        async def receive():
            return next(messages)
        async def send(message):
            output.append(message)
        headers = [(b"content-type", b"application/json")]
        if declared is not None:
            headers.append((b"content-length", declared.encode()))
        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/body", "raw_path": b"/body", "query_string": b"", "headers": headers, "server": ("test", 80), "client": ("test", 1)}, receive, send)
        return output
    output = asyncio.run(run([b'{"x":', b'123}']))
    assert output[0]["status"] == 413
    assert json.loads(output[1]["body"])["error"]["code"] == "body_too_large"
    output = asyncio.run(run([b'{"x":', b'12}']))
    assert output[0]["status"] == 200
