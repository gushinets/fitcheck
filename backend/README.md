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
