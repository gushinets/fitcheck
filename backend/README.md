# FitCheck backend

Independent Python 3.12+ service. It does not require anytoolai-platform, a database, login service or provider keys for foundation startup.

```sh
cd backend
uv sync --locked
uv run python -m fitcheck_backend
```

With FITCHECK_AUTH_ENABLED=false, GET http://127.0.0.1:8000/health/live and /health/ready return `{"status":"ok","stage":"foundation"}`. Enabled auth uses stage auth_storage; readiness checks database connectivity and the packaged migration head, and reports email configured/unconfigured separately. Liveness does not depend on PostgreSQL.

Settings use the FITCHECK_ prefix (see `.env.example`). Environment is dev/test/production, port 1–65535, body limit 1–16777216 bytes, log level debug/info/warning/error/critical. Origins are a JSON array of exact origins, e.g. `["http://localhost:3000","chrome-extension://YOUR_ID"]`. Defaults bind localhost:8000 with no CORS origins. Configuration never automatically loads dotenv files. Export environment variables explicitly; never commit secrets.

```sh
uv run pytest -q
```

Storage and migrations are implemented in ANY-644. Server authentication is implemented in ANY-645; profile API is ANY-646, extraction ANY-647, provider gateway ANY-648, durable jobs ANY-649, history ANY-650, guest quotas ANY-651, local import ANY-652, UI integration ANY-653 and production operations ANY-654. Current Next.js APIs/web/extension remain active until integration.

The HTTP boundary generates X-Request-ID; client-supplied IDs are ignored. Errors are `{error:{code,message,requestId,details}}`; details contain field locations/codes only. Validation errors use 400, 404/405 share the envelope, unexpected exceptions use a safe 500. Actual body bytes are limited even without/trusting Content-Length; mutation bodies must use application/json. Logs contain request ID/method/path/status only; uvicorn access logging is disabled to avoid query logging.

CORS allows only configured origins and explicit methods/headers. Web http(s) origins allow credentials; extension origins do not. Cross-origin rejection is not authorization or CSRF protection; enabled authentication resolves server identity and enforces cookie mutation Origin/CSRF checks separately.

## API contracts

```sh
# From backend/
uv run python scripts/export_openapi.py
uv run python scripts/export_openapi.py --check
```

Committed `../contracts/fitcheck.openapi.json` is the full roadmap contract. Live `/openapi.json` contains implemented health and account/auth routes; disabled auth returns 503. Remaining full-export business routes are annotated `x-fitcheck-implementation: planned` and `x-fitcheck-owner-task`; they return 404 in the current runtime. Export requires no environment/DB/provider setup. DTOs use camelCase, reject unknown new-request fields, and omit missing optional values (explicit null only for clearable resources). Legacy import accepts and discards desiredMonthlyIncome and never accepts local passwords/tokens.

Cookie mutations require verified Origin and X-CSRF-Token when implemented; extension login uses exact redirect allowlist and PKCE S256. Idempotency-Key is required by contracts for job starts, reanalysis, guest claim and import. Identity, ownership, quota and atomic admission enforcement belong to the annotated implementing tasks.

From the repository root, `pnpm backend:types` regenerates TypeScript and `pnpm backend:types:check` verifies drift without writing. Generated types live in lib/backend/generated/schema.ts; edit Python DTOs instead. lib/backend/client.ts is a transport factory with mandatory success validation, structured errors, AbortSignal and configurable credentials. Its base URL is /backend/v1 for future web proxy or an API origin ending /v1 for extension use. Route arguments are relative to that base; external URLs/traversal are rejected. Redirects and automatic mutation retries are disabled. Existing UI does not import this transport yet.

## Verification and rollout

CI runs backend pytest and OpenAPI drift with Python 3.12/uv 0.12.7, plus generated TypeScript drift and the existing frontend test/typecheck/lint/Webpack/extension builds. For a fresh Node install run `pnpm install --frozen-lockfile` (postinstall prepares WXT types); `pnpm exec next typegen` generates Next route declarations when needed.

Storage and authentication are implemented separately from the remaining business/LLM routes. A persistent development database was provisioned separately at the user's request on 2026-10-12; see the deployment record below. At ANY-653 the web proxy `/backend/*` and extension origin/identity configuration connect implemented API operations; old LLM routes must enforce the same policies or be disabled. ANY-654 still covers production operations, worker deployment, automated migration ordering and backup/restore validation.

## Container deployment

The user requested deployment after completing foundation. Build from the repository root:

```sh
docker build -f backend/Dockerfile -t fitcheck-api backend
docker run --rm -p 8000:8000 fitcheck-api
```

The image installs locked production dependencies, runs as UID 10001, binds port 8000 and checks /health/ready. Build context is backend/; dotenv, local environments and test files are excluded. Dokploy uses repository fitcheck, branch dev, build path /, Dockerfile backend/Dockerfile and context backend. API is a separate application in FitCheck development, with its own domain and exact allowed web origin. It remains a foundation service: business routes and UI integration are later tasks.

### Persistent development database

On 2026-10-12, Dokploy's FitCheck `development` environment received the separate `fitcheck-postgres-dev` service (`postgres:17`). Its internal service name is `fitcheck-postgres-dev-87obt4`; the named volume `fitcheck-postgres-dev-87obt4-data` mounts at `/var/lib/postgresql/data`. No external PostgreSQL port is published. Database `fitcheck` and its credentials belong exclusively to FitCheck. `FITCHECK_DATABASE_URL` is saved in the API application's secret environment; existing API settings were preserved. Never commit or print this value.

The API was redeployed with the database configuration. Explicit `upgrade` and `check` ran inside the deployed API container, using its installed virtual environment:

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade
/app/.venv/bin/python -m fitcheck_backend.storage.migrate check
```

The system `python` in a container shell does not contain the application dependencies; use the absolute virtual-environment path above. Revision `0002`, 17 application tables plus `alembic_version`, and five application triggers were verified through the API container's database connection. A temporary-table write/read probe passed. After reloading PostgreSQL, the same revision, tables and triggers remained present and the schema check passed again. `/health/live` and `/health/ready` remain foundation checks and do not prove database connectivity; run the migration/schema checks separately. Business routes, client integration, scheduled retention and production backup/restore remain their roadmap tasks.

## PostgreSQL storage and migrations

FitCheck owns a separate PostgreSQL database. Storage uses SQLAlchemy 2.0/psycopg 3; Alembic migration files are included in the installed wheel and Docker image. Imports and API startup do not connect to the database. `FITCHECK_DATABASE_URL` is required only when using storage/migrations and is treated as a secret. Supported DSNs are PostgreSQL URLs, normalized to `postgresql+psycopg`; alternate drivers, malformed authority/host and connection-identity overrides in query parameters are rejected. Allowed query options are sslmode, sslrootcert, sslcert, sslkey, sslpassword, client_encoding and application_name. TLS sslpassword is moved to driver arguments and removed from the engine URL; authority passwords with special characters must be percent-encoded.

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

## Authentication rollout and operations

ANY-645 implements 14 account/auth operations. `FITCHECK_AUTH_ENABLED=false` preserves database-independent foundation startup and makes auth operations return safe 503. To enable: apply/check migration `0003` using `/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade` and `check`, configure `FITCHECK_DATABASE_URL`, a unique `FITCHECK_AUTH_SECRET` (hex encoding of at least 32 random bytes), an exact `FITCHECK_AUTH_WEB_BASE_URL`, and exact `FITCHECK_ALLOWED_ORIGINS`, then set `FITCHECK_AUTH_ENABLED=true` and restart API. The API never migrates on startup. Enabled readiness returns 503 if DB is unreachable or revision differs from the installed package head; SMTP-unconfigured readiness is 200 with `dependencies.email=unconfigured`.

Web flow: GET `/v1/auth/csrf` with trusted Origin issues a 15-minute pre-login HttpOnly cookie and `{csrfToken}`. POST `/v1/auth/register` or `/login` sends the same Origin, `X-CSRF-Token` and JSON `{email,password}` with cookies enabled. Production uses Secure HttpOnly `__Host-fitcheck_session`, SameSite=Lax, Path=/, no Domain; development uses `fitcheck_session`. Registration returns 201 and login 200 with `{user,csrfToken}`; raw web session token is never JSON. GET `/v1/auth/session` recovers CSRF after page reload, GET `/v1/me` returns the current user. Cookie mutations require Origin and CSRF; login/signup CSRF comes from bootstrap, not a previous account session. The future same-origin web proxy must supply the trusted Origin for bootstrap GET when the browser omits it; integration must account for this rather than letting clients bypass Origin validation.

New/reset passwords have 15–128 Unicode characters, no stripping/rewriting/composition rules; login/deletion candidates have 1–128. Passwords use salted Argon2id (64 MiB, 3 iterations, parallelism 4); each runtime limits expensive hashing to two concurrent operations outside transactions. Unknown email/wrong password share 401 invalid_credentials. Duplicate registration uses 409 registration_conflict, an explicitly accepted enumeration trade-off. Existing IndexedDB email/password digests cannot authenticate a server account. Sessions/tokens are stored as digests; auth responses and errors use no-store. One request may authenticate by web cookie or extension bearer, never both.

Configure all SMTP settings together: HOST/PORT/USERNAME/PASSWORD/FROM/SECURITY, with `smtps` or mandatory `starttls`, certificate verification and 10-second timeout. Secrets stay in the deployment environment. Without SMTP, registration, POST `/v1/auth/verify-email/request` and `/password-reset/request` return 503 email_unavailable uniformly before identity/token writes. Existing-account login/me/session/logout/confirm/deletion can still operate. Production has no fake/console mailer.

SMTP registration commits a pending user and verification token before sending; send failure returns 503 without a session cookie, leaving a recoverable pending account. Use login and resend once delivery recovers; retrying registration returns duplicate conflict. Configured resend/reset-request 204 means request accepted, including unknown email, and never confirms inbox delivery. Delivery failure logs only purpose/category; user may retry after rate-limit cooldown. Mail links target future web `/auth/verify-email` and `/auth/password-reset` pages with token in the URL fragment. These UI pages remain ANY-653; until integrated, an operator can consume a received token through the corresponding POST API. Verification POST additionally requires the matching user's web session and CSRF, preventing an unsolicited link from verifying an attacker's pre-registered account. Reset-confirm takes `{token,password}`, trusted Origin, revokes all sessions/codes and does not log the user in automatically.

Pending accounts may use me/session/resend/logout/delete. Account business operations and extension authorization require verified email. Future profile/job/report/annotation/import services must use `verified_principal` and `load_owned`; the latter filters resource ID plus server-resolved owner and returns 404 for missing/foreign data. DELETE `/v1/me` requires current password in JSON, current session and transport protection; it atomically deletes private account/claimed-guest data and anonymizes provider-call links. Concurrent guest claims cause fresh graph re-enumeration, up to three attempts, then safe 409 ownership_conflict.

Extension browser login: POST `/v1/auth/extension/authorize` with verified web session/CSRF sends redirectUri, codeChallenge, codeChallengeMethod=S256 and state. Callback must exactly match configured `https://<32-letter-extension-id>.chromiumapp.org/<path>` without query/fragment; empty allowlist denies authorization. Web code expires in 2 minutes and is bound to the issuing session. POST `/v1/auth/extension/token` from an exact configured chrome-extension Origin exchanges `{code,codeVerifier,redirectUri}` once for a one-hour bearer. Client validates echoed state. Revoke uses the extension bearer; cookies are not sent. There is no refresh token; repeat browser authorization when expired. The local web/extension UI remains on its existing adapter until ANY-653.

Absolute TTL: web 7 days, extension 1 hour, verify 24 hours, reset 30 minutes, bootstrap 15 minutes. Fixed-window limits are shared in PostgreSQL: login 10/email and 60/IP per15m; register5/IP/hour; verify/reset requests3/email and20/IP/hour; token confirmation/exchange30/IP/15m; bootstrap60/IP/15m; delete5/user/15m. Counters include rejected attempts and survive business rollbacks; 429 includes Retry-After. Expired limiter rows are deleted in batches of at most100; general retention scheduling remains future work. HMAC hides raw email/IP in buckets. By default forwarded IP headers are ignored; `FITCHECK_TRUSTED_PROXY_IPS` accepts explicit proxy IP/CIDR only. Inspect the Dokploy proxy network before enabling trust; never use `*`. Without proxy configuration IP budgets aggregate at the proxy while per-email limits still apply.

Unit/integration tests and container smoke use disposable PostgreSQL only. SMTP-adapter tests replace the external SMTP transport, preserving TLS/message/error behavior; real sending requires credentials supplied later. Auth code/0003 in this branch are not a claim that production auth or UI integration has been deployed. Production backups/restore and automated deployment ordering remain ANY-654.

## Retention contract

| Data | Retention |
| --- | --- |
| Account profiles/revisions/history | Until account deletion |
| Unclaimed guest data | 30 days after guest expiry |
| Expired/revoked sessions and consumed/expired auth tokens | 7 days after expiry/revocation |
| Terminal jobs and idempotency records | At least 30 days after completion |
| Anonymous provider metrics | 90 days |

Account deletion removes the ownership graph, including claimed guests' remaining private profile/draft data. Ledger owner/job/request-key links are cleared before cascading deletion; only technical metrics survive. Job cleanup must detach optional analysis and ledger links before deleting a referenced job, preserving its report snapshot. Guest history transferred to an account follows account retention. Quota/import deduplication records remain for their policy/account lifetime. Cleanup scheduling, account deletion HTTP flow and configurable TTL enforcement are future service/operations tasks; ANY-644 defines the policy and tests the storage behavior.
