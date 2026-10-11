# FitCheck backend

Independent Python 3.12+ service. It does not require anytoolai-platform, a database, login service or provider keys for foundation startup.

```sh
cd backend
uv sync --locked
uv run python -m fitcheck_backend
```

GET http://127.0.0.1:8000/health/live and /health/ready return `{"status":"ok","stage":"foundation"}`. Readiness currently checks application configuration/routes, not future storage/auth/worker dependencies.

Settings use the FITCHECK_ prefix (see `.env.example`). Environment is dev/test/production, port 1–65535, body limit 1–16777216 bytes, log level debug/info/warning/error/critical. Origins are a JSON array of exact origins, e.g. `["http://localhost:3000","chrome-extension://YOUR_ID"]`. Defaults bind localhost:8000 with no CORS origins. Configuration never automatically loads dotenv files. Export environment variables explicitly; never commit secrets.

```sh
uv run pytest -q
```

Database and migrations are ANY-644, authentication ANY-645, profiles ANY-646, extraction ANY-647, provider gateway ANY-648, durable jobs ANY-649, history ANY-650, guest quotas ANY-651, local import ANY-652, UI integration ANY-653 and production operations ANY-654. Current Next.js APIs/web/extension remain active until integration.

The HTTP boundary generates X-Request-ID; client-supplied IDs are ignored. Errors are `{error:{code,message,requestId,details}}`; details contain field locations/codes only. Validation errors use 400, 404/405 share the envelope, unexpected exceptions use a safe 500. Actual body bytes are limited even without/trusting Content-Length; mutation bodies must use application/json. Logs contain request ID/method/path/status only; uvicorn access logging is disabled to avoid query logging.

CORS allows only configured origins and explicit methods/headers. Web http(s) origins allow credentials; extension origins do not. Cross-origin rejection is not authorization or CSRF protection; business identity/ownership and cookie mutation Origin/CSRF checks arrive in ANY-645.
