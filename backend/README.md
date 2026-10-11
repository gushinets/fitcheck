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

Storage and migrations are implemented in ANY-644. Business authentication is ANY-645, profile API ANY-646, extraction ANY-647, provider gateway ANY-648, durable jobs ANY-649, history ANY-650, guest quotas ANY-651, local import ANY-652, UI integration ANY-653 and production operations ANY-654. Current Next.js APIs/web/extension remain active until integration.

The HTTP boundary generates X-Request-ID; client-supplied IDs are ignored. Errors are `{error:{code,message,requestId,details}}`; details contain field locations/codes only. Validation errors use 400, 404/405 share the envelope, unexpected exceptions use a safe 500. Actual body bytes are limited even without/trusting Content-Length; mutation bodies must use application/json. Logs contain request ID/method/path/status only; uvicorn access logging is disabled to avoid query logging.

CORS allows only configured origins and explicit methods/headers. Web http(s) origins allow credentials; extension origins do not. Cross-origin rejection is not authorization or CSRF protection; business identity/ownership and cookie mutation Origin/CSRF checks arrive in ANY-645.

## API contracts

```sh
# From backend/
uv run python scripts/export_openapi.py
uv run python scripts/export_openapi.py --check
```

Committed `../contracts/fitcheck.openapi.json` is the full roadmap contract. Live `/openapi.json` contains only implemented health routes. Full-export business routes are annotated `x-fitcheck-implementation: planned` and `x-fitcheck-owner-task`; they return 404 in the current runtime. Export requires no environment/DB/provider setup. DTOs use camelCase, reject unknown new-request fields, and omit missing optional values (explicit null only for clearable resources). Legacy import accepts and discards desiredMonthlyIncome and never accepts local passwords/tokens.

Cookie mutations require verified Origin and X-CSRF-Token when implemented; extension login uses exact redirect allowlist and PKCE S256. Idempotency-Key is required by contracts for job starts, reanalysis, guest claim and import. Identity, ownership, quota and atomic admission enforcement belong to the annotated implementing tasks.

From the repository root, `pnpm backend:types` regenerates TypeScript and `pnpm backend:types:check` verifies drift without writing. Generated types live in lib/backend/generated/schema.ts; edit Python DTOs instead. lib/backend/client.ts is a transport factory with mandatory success validation, structured errors, AbortSignal and configurable credentials. Its base URL is /backend/v1 for future web proxy or an API origin ending /v1 for extension use. Route arguments are relative to that base; external URLs/traversal are rejected. Redirects and automatic mutation retries are disabled. Existing UI does not import this transport yet.

## Verification and rollout

CI runs backend pytest and OpenAPI drift with Python 3.12/uv 0.12.7, plus generated TypeScript drift and the existing frontend test/typecheck/lint/Webpack/extension builds. For a fresh Node install run `pnpm install --frozen-lockfile` (postinstall prepares WXT types); `pnpm exec next typegen` generates Next route declarations when needed.

Storage implementation does not provision a production database or expose business auth/LLM routes. No Dokploy routing/secrets/applications change here. At ANY-653 the web proxy `/backend/*` and extension origin/identity configuration connect implemented API operations; old LLM routes must enforce the same policies or be disabled. At ANY-654 deploy API/worker/PostgreSQL and a single migration process, extend readiness to real dependencies and verify backup/restore.

## Container deployment

The user requested deployment after completing foundation. Build from the repository root:

```sh
docker build -f backend/Dockerfile -t fitcheck-api backend
docker run --rm -p 8000:8000 fitcheck-api
```

The image installs locked production dependencies, runs as UID 10001, binds port 8000 and checks /health/ready. Build context is backend/; dotenv, local environments and test files are excluded. Dokploy uses repository fitcheck, branch dev, build path /, Dockerfile backend/Dockerfile and context backend. API is a separate application in FitCheck development, with its own domain and exact allowed web origin. It remains a foundation service: business routes and UI integration are later tasks.

## PostgreSQL storage and migrations

FitCheck owns a separate PostgreSQL database. Storage uses SQLAlchemy 2.0/psycopg 3; Alembic migration files are included in the installed wheel and Docker image. Imports and API startup do not connect to the database. `FITCHECK_DATABASE_URL` is required only when using storage/migrations and is treated as a secret. Supported DSNs are PostgreSQL URLs, normalized to `postgresql+psycopg`; alternate drivers and connection-identity overrides in URL query parameters are rejected.

Connection defaults: pool size 2 (1–20), overflow 3 (0–20), pool timeout 5 seconds (1–60), statement timeout 15000 ms (1–300000), connect timeout 5 seconds. Migration connections use a 120000 ms statement timeout. The migration runner waits at most 10 seconds for a PostgreSQL session advisory lock; failure rolls back its transaction and releases the lock. API/worker processes never run migrations themselves.

Local disposable PostgreSQL 17 and checks, from `backend/`:

```sh
uv sync --locked --python 3.12
docker compose -p fitcheck-any644 -f compose.test.yaml up -d --wait
export FITCHECK_TEST_DATABASE_URL='postgresql+psycopg://fitcheck_test:fitcheck_test@127.0.0.1:55464/fitcheck_test'
uv run pytest -m 'not integration' -q
uv run pytest -m integration -q
export FITCHECK_DATABASE_URL="$FITCHECK_TEST_DATABASE_URL"
uv run python -m fitcheck_backend.storage.migrate upgrade
uv run python -m fitcheck_backend.storage.migrate check
docker compose -p fitcheck-any644 -f compose.test.yaml stop
```

Integration tests require the explicit test DSN and a database name ending in `_test`; they truncate personal tables and exercise destructive downgrade/re-upgrade. **Never point them at a database whose data you need.** They never fall back to `FITCHECK_DATABASE_URL`. Plain pytest runs unit/wheel tests only; an explicit integration run fails when its DSN is absent. The wheel test builds and installs the locked runtime dependencies into an isolated temporary environment using uv, then verifies resources from a different working directory.

To remove the disposable containers/volumes after local testing, use `docker compose -p fitcheck-any644 -f compose.test.yaml down --volumes` only when those test data may be destroyed. Initial migration downgrade removes tables and data; it is a test rollback, **not production recovery**. Tests downgrade through Alembic with their explicit disposable connection. For deployment run `python -m fitcheck_backend.storage.migrate upgrade` once with the target DB secret, then start API and worker. Run `check` to detect relational schema drift. Production backup/restore and deployment orchestration are ANY-654.

Profiles use integer DB revisions, exposed as decimal strings in the existing API DTO. Compare-and-swap updates append revisions; a stale expected revision raises `ProfileRevisionConflict`. Idempotent job admission hashes normalized input and uses a DB unique constraint; a changed payload with the same owner/type/key raises `IdempotencyConflict`. Owner IDs must come from an authenticated application service, never directly from untrusted HTTP input. Guest transfer and deletion helpers are storage primitives, not authorization endpoints. Job creation takes a shared owner lock to synchronize with claim/deletion; claimed guests cannot create jobs. Pending guest jobs or outstanding quota reservations prevent transfer. Profile/preferences/draft of the account are preserved during transfer.

Snapshot and result payloads use explicit Pydantic codecs; persisted version `fitcheck.analysis.v1` is currently supported. Unknown snapshot versions are rejected. DB triggers protect immutable payloads; mutable feedback/status are separate annotations. The DB permits low-level maintenance writes, so application services must use the codecs on reads and writes. Legacy desiredMonthlyIncome is discarded before persistence/hashing. Provider ledger contains technical metrics, not profile/vacancy text or access tokens. Never log raw DB exceptions: PostgreSQL diagnostic DETAIL may contain row values even when SQLAlchemy hides bound parameters. HTTP boundaries and migration CLI return safe messages.

## Retention contract

| Data | Retention |
| --- | --- |
| Account profiles/revisions/history | Until account deletion |
| Unclaimed guest data | 30 days after guest expiry |
| Expired/revoked sessions and consumed/expired auth tokens | 7 days after expiry/revocation |
| Terminal jobs and idempotency records | At least 30 days after completion |
| Anonymous provider metrics | 90 days |

Account deletion removes the ownership graph, including claimed guests' remaining private profile/draft data. Ledger owner/job/request-key links are cleared before cascading deletion; only technical metrics survive. Job cleanup must detach optional analysis and ledger links before deleting a referenced job, preserving its report snapshot. Guest history transferred to an account follows account retention. Quota/import deduplication records remain for their policy/account lifetime. Cleanup scheduling, account deletion HTTP flow and configurable TTL enforcement are future service/operations tasks; ANY-644 defines the policy and tests the storage behavior.
