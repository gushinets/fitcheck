# FitCheck backend

Independent Python 3.12+ service. It does not require anytoolai-platform, a database, login service or provider keys for foundation startup.

```sh
cd backend
uv sync --locked
uv run python -m fitcheck_backend
```

With FITCHECK_AUTH_ENABLED=false, GET http://127.0.0.1:8000/health/live and /health/ready return `{"status":"ok","stage":"foundation"}`. Enabled auth uses stage auth_storage; readiness checks database connectivity and the packaged migration head, and reports email configured/unconfigured separately. Liveness does not depend on PostgreSQL.

Settings use the FITCHECK_ prefix (see `.env.example`). Environment is dev/test/production, port 1–65535, body limit 1–16777216 bytes, log level debug/info/warning/error/critical. Origins are a JSON array of exact origins, e.g. `["http://localhost:3000"]`. Defaults bind localhost:8000 with no CORS origins. Configuration never automatically loads dotenv files. Export environment variables explicitly; never commit secrets.

```sh
uv run pytest -q
```

Storage and migrations are implemented in ANY-644, server authentication in ANY-645, profile/preferences/draft API in ANY-646, vacancy extraction in ANY-647 and the LLM gateway/services in ANY-648. Remaining tasks: durable jobs ANY-649, history ANY-650, guest quotas ANY-651, local import ANY-652, UI integration ANY-653 and production operations ANY-654. Current Next.js APIs and website remain active until integration.

The HTTP boundary generates X-Request-ID; client-supplied IDs are ignored. Errors are `{error:{code,message,requestId,details}}`; details contain field locations/codes only. Validation errors use 400, 404/405 share the envelope, unexpected exceptions use a safe 500. Actual body bytes are limited even without/trusting Content-Length; mutation bodies must use application/json. Logs contain request ID/method/path/status only; uvicorn access logging is disabled to avoid query logging.

CORS allows only configured origins and explicit methods/headers. Only exact website HTTP(S) origins are supported, with credentials. Cross-origin rejection is not authorization or CSRF protection; enabled authentication resolves server identity and enforces cookie mutation Origin/CSRF checks separately.

## API contracts

```sh
# From backend/
uv run python scripts/export_openapi.py
uv run python scripts/export_openapi.py --check
```

Committed `../contracts/fitcheck.openapi.json` is the full roadmap contract. Live `/openapi.json` contains implemented health, account/auth, profile, preferences, draft and extraction routes; disabled auth returns 503. Remaining full-export business routes are annotated `x-fitcheck-implementation: planned` and `x-fitcheck-owner-task`; they return 404 in the current runtime. Export requires no environment/DB/provider setup. DTOs use camelCase, reject unknown new-request fields, and omit missing optional values (explicit null for clearable resources and initial expectedRevision). Legacy import accepts and discards desiredMonthlyIncome and never accepts local passwords/tokens.

Cookie mutations require verified Origin and X-CSRF-Token. Idempotency-Key is required by contracts for job starts, reanalysis, guest claim and import. Identity, ownership, quota and atomic admission enforcement belong to the annotated implementing tasks.

From the repository root, `pnpm backend:types` regenerates TypeScript and `pnpm backend:types:check` verifies drift without writing. Generated types live in lib/backend/generated/schema.ts; edit Python DTOs instead. lib/backend/client.ts is a transport factory with mandatory success validation, structured errors, AbortSignal and configurable credentials. Its base URL is /backend/v1 for the future website proxy or a configured API origin ending /v1. Route arguments are relative to that base; external URLs/traversal are rejected. Redirects and automatic mutation retries are disabled. Existing UI does not import this transport yet.

## Profile, revisions, preferences and draft (ANY-646)

All routes below require a verified account through a web session cookie. The owner comes from the session; request owner/user IDs are rejected.
Mutations require trusted website Origin and X-CSRF-Token. Responses use Cache-Control: no-store.

| Method / route | Behavior |
| --- | --- |
| `GET /v1/profile` | Current `{revision, profile}`; 404 until a profile exists |
| `PUT /v1/profile` | Required `{expectedRevision, profile}`; null creates revision "1", a canonical positive decimal string updates that revision |
| `GET /v1/profile/revisions/{revision}` | An immutable historical profile owned by the account; 404 if absent |
| `GET /v1/profile/revisions/{revision}/comparison` | `{saved, current, changedFields}`; field names are camelCase and sorted |
| `GET /v1/preferences` | `{locale}`; defaults to "en" before the first save |
| `PUT /v1/preferences` | Persist `{locale: "en" \| "ru"}` |
| `GET /v1/draft` | `{vacancy, locale}` or null |
| `PUT /v1/draft` | Persist a draft, or send JSON null to clear; a missing body is invalid |
| `DELETE /v1/draft` | Idempotent clear, 204 |

Profile writes compare the expected revision atomically in the caller transaction.
Concurrent initial creation and stale writes return 409 / profile_revision_conflict;
reload the profile and resolve the conflict before retrying. Strings such as "0",
"01" and "r1" are invalid revisions (400); counters fit PostgreSQL INTEGER.
After trimming text and removing duplicate skills case-insensitively (first display
spelling/order retained), identical profile payloads retain the current revision.
Other payload changes append a new immutable revision. A stale no-op still conflicts.
Skill levels use lowercase skill keys and preserve primary/confident/basic;
currency and monetary values are preserved. New profile requests reject
desiredMonthlyIncome. LegacyProfile storage encoding discards legacy income.

Preferences/draft writes replace the account's value; they do not create profile
revisions. Data is persisted in PostgreSQL and available to other authenticated
devices. Analysis snapshots already contain profileRevision and the used profile;
updating the profile preserves that historical revision. ANY-649/650 will connect
analysis execution/history to these revisions; ANY-652/653 handle local import and
UI adapters. The website-only release uses the fresh initial migration described below.

## Vacancy extraction (ANY-647)

`POST /v1/extractions` accepts `{"type":"url","url":"https://example.com/job"}` or
`{"type":"text","text":"Title\nDescription…"}` and returns `{vacancy}` with a new UUID.
It requires a verified web account, trusted Origin and X-CSRF-Token. Guest admission
is deferred to ANY-651; switching the website to this API belongs to ANY-653.
The returned vacancy is editable and does not overwrite a saved draft. After review,
save it explicitly with `PUT /v1/draft` or pass it to the future analysis API.

The parser removes HTML navigation/scripts, uses JobPosting JSON-LD and visible
Freelancer project content, and extracts skills and hourly/fixed budgets in USD,
EUR and RUB. Monthly/annual salaries are not treated as hourly rates. Explicit
competition data uses optional `proposalCount`, `averageBid`, `averageBidCurrency`;
unknown values remain absent (null input is accepted and omitted on output).
`provenance` maps extracted fields to `json_ld`, `html` or `text`.
Existing draft/snapshot JSON storage accepts these fields without a migration.

URL fetching permits only HTTP(S) public addresses, validates every resolved address
and redirect, and pins connections to the checked IP while verifying HTTPS against
the original hostname. It forwards no account cookies or credentials. Limits are
2,000 URL characters, three redirects, eight seconds total, 64 KiB response headers,
and 1 MB body (3 MB for exact Freelancer project URLs). Failed fetches consume the
same quota: 30 requests per account/minute and 120 per IP/15 minutes, persisted in
PostgreSQL. A rejection returns 429 with Retry-After.
Safe structured errors suggest manual input when a page is blocked, unsupported,
too large, unavailable, or contains insufficient vacancy text. Text must have at
least a two-character title and a 30-character description; request limits are
documented in OpenAPI. No LLM or provider credentials are needed.

## LLM gateway and application services (ANY-648)

`fitcheck_backend.llm.runtime.LlmRuntime(settings, engine)` owns a cached LiteLLM
adapter/gateway and PydanticAI structured executors. Use it as an async context
manager or call `aclose()` at shutdown; the injected PostgreSQL engine remains
owned by the caller. Only `llm/litellm_adapter.py` imports provider SDKs; only
`llm/structured.py` imports PydanticAI. No separate gateway/proxy service is needed.

`runtime.analysis.analyze(owner_id=..., profile_revision=..., vacancy=..., locale=...,
job_id=None)` reads the immutable revision and last ten owner-scoped calibration
entries, then returns `{analysis, snapshot}` as an internal typed result.
`runtime.suggestions.suggest(owner_id=..., specialization=..., locale=..., job_id=None)`
returns up to ten unique skills. An optional job must belong to the owner and have
the matching job type. Neither service publishes an analysis nor changes job state;
ANY-649 will call them from its durable worker. Public job routes remain planned.

`FITCHECK_DEEPSEEK_API_KEY` is optional for API startup and required for provider
calls. Missing key returns safe `service_unavailable` before DB/provider work.
Provider/model/prompts are server-owned: initial policy uses DeepSeek
`deepseek-v4-flash`, thinking disabled, JSON-object output, temperature zero.
PydanticAI owns schema prompting/validation; the gateway owns HTTP and ledger.
No request DTO accepts provider/model/system prompt or client calibration memory.

Each structured operation has at most two semantic attempts, each with at most
two transport attempts. Analysis generation plus grounding audit share an eight-call
hard cap and 120-second total deadline; suggestions have four calls and 60 seconds.
Context reads count toward the deadline. Individual calls are at most 45 seconds;
backoff/Retry-After must fit the remaining time. Output caps are 1200 tokens for
generation, 1000 for audit and 500 for suggestions. SDK retries/fallback are disabled;
a per-attempt HTTP-send guard also blocks SDK-internal extra sends. Clients verify
TLS, permit only the fixed provider destination and do not follow redirects.

Basic skills are not professional strengths. The model selects unique allowed
strength IDs; the server renders text and provenance. Currency comparisons retain
unknown/mismatched currency and minimum-only hourly budget semantics. Fixed budgets
are not compared to hourly rates without effort estimates. Narrative audit checks
profile/task grounding before success. The server returns `verdictThreshold: 70`
and computes GO only at score ≥ 70. Legacy results may omit this new field.
Nullable `fitCondition` is a forward contract for ANY-576 and is not generated here;
competition evidence is preserved in vacancy snapshots, with scoring deferred to ANY-575.

Additive migration `0002` extends `provider_calls` with prompt/schema/policy versions,
semantic/transport indices and latency_ms. Apply it before restarting the upgraded
API/worker; existing initial `0001` and payloads remain valid. Generation and audit
record their respective schema versions. Start rows are separately committed before
network I/O; final metrics survive operation failures and do not hold a DB connection
during requests. Ledger failures stop the operation. Validation failures retain usage
while marking the call failed; a failure to finish a row leaves `started` for future
reconciliation. Unknown tokens/cost remain null. Costs use available SDK pricing
metadata and are estimates; no raw requests/responses, secrets or personal content
are persisted in ledger or SDK telemetry.

Deterministic mock/HTTP-transport tests use the real PydanticAI/LiteLLM adapters.
Optional paid canary, from `backend/`, requires an explicitly supplied key and opt-in:
`FITCHECK_RUN_LLM_CANARY=1 uv run --locked pytest tests/analysis/test_live_canary.py -q`.
It uses only anonymized fixtures and in-process metrics; PostgreSQL accounting is
tested separately on disposable PG. Without opt-in/key it is reported as skipped.
Library behavior references: [PydanticAI output](https://pydantic.dev/docs/ai/core-concepts/output/),
[LiteLLM SDK](https://docs.litellm.ai/docs/python_sdk).

## Verification and rollout

CI runs backend pytest and OpenAPI drift with Python 3.12/uv 0.12.7, plus generated TypeScript drift and the existing frontend test/typecheck/lint and website builds. For a fresh Node install run `pnpm install --frozen-lockfile`; `pnpm exec next typegen` generates Next route declarations when needed.

Storage and authentication are implemented separately from the remaining business/LLM routes. A persistent development database was provisioned separately at the user's request on 2026-10-12; see the deployment record below. At ANY-653 the web proxy `/backend/*` connects implemented API operations; old LLM routes must enforce the same policies or be disabled. ANY-654 still covers production operations, worker deployment, automated migration ordering and backup/restore validation.

## Container deployment

The user requested deployment after completing foundation. Build from the repository root:

```sh
docker build -f backend/Dockerfile -t fitcheck-api backend
docker run --rm -p 8000:8000 fitcheck-api
```

The image installs locked production dependencies, runs as UID 10001, binds port 8000 and checks /health/ready. Build context is backend/; dotenv, local environments and test files are excluded. Dokploy uses repository fitcheck, branch dev, build path /, Dockerfile backend/Dockerfile and context backend. API is a separate application in FitCheck development, with its own domain and exact allowed web origin. It remains a foundation service: business routes and UI integration are later tasks.

### Persistent development database (historical rollout)

On 2026-10-12, Dokploy's FitCheck `development` environment received the separate `fitcheck-postgres-dev` service (`postgres:17`). Its internal service name is `fitcheck-postgres-dev-87obt4`; the named volume `fitcheck-postgres-dev-87obt4-data` mounts at `/var/lib/postgresql/data`. No external PostgreSQL port is published. Database `fitcheck` and its credentials belong exclusively to FitCheck. `FITCHECK_DATABASE_URL` is saved in the API application's secret environment; existing API settings were preserved. Never commit or print this value.

The API was redeployed with the database configuration. Explicit `upgrade` and `check` ran inside the deployed API container, using its installed virtual environment:

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade
/app/.venv/bin/python -m fitcheck_backend.storage.migrate check
```

The system `python` in a container shell does not contain the application dependencies; use the absolute virtual-environment path above. Revision `0002`, 17 application tables plus `alembic_version`, and five application triggers were verified through the API container's database connection. A temporary-table write/read probe passed. After reloading PostgreSQL, the same revision, tables and triggers remained present and the schema check passed again. `/health/live` and `/health/ready` remain foundation checks and do not prove database connectivity; run the migration/schema checks separately. Business routes, client integration, scheduled retention and production backup/restore remain their roadmap tasks.

## PostgreSQL storage and migrations

Current migrations start from a single website-only `0001` baseline. It creates all
18 application tables, authentication rate buckets, constraints/indexes and the
five payload/ledger triggers. The pre-baseline migration chain was removed at the
user's request. Current additive revisions are `0002` (provider metadata) and
`0003` (worker execution token), with current head `0003`. Run the baseline on an empty database; its revision number must not be stamped
over an existing schema. Existing development databases from the earlier chain
need an explicitly authorized schema reset. Deployment history below/above records
the earlier rollout and does not describe the new baseline.

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

ANY-645 implements 11 website account/auth operations. `FITCHECK_AUTH_ENABLED=false` preserves database-independent foundation startup and makes auth operations return safe 503. To enable: apply/check initial migration `0001` using `/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade` and `check`, configure `FITCHECK_DATABASE_URL`, a unique `FITCHECK_AUTH_SECRET` (hex encoding of at least 32 random bytes), an exact `FITCHECK_AUTH_WEB_BASE_URL`, and exact `FITCHECK_ALLOWED_ORIGINS`, then set `FITCHECK_AUTH_ENABLED=true` and restart API. The API never migrates on startup. Enabled readiness returns 503 if DB is unreachable or revision differs from the installed package head; SMTP-unconfigured readiness is 200 with `dependencies.email=unconfigured`.

Web flow: GET `/v1/auth/csrf` with trusted Origin issues a 15-minute pre-login HttpOnly cookie and `{csrfToken}`. POST `/v1/auth/register` or `/login` sends the same Origin, `X-CSRF-Token` and JSON `{email,password}` with cookies enabled. Production uses Secure HttpOnly `__Host-fitcheck_session`, SameSite=Lax, Path=/, no Domain; development uses `fitcheck_session`. Registration returns 201 and login 200 with `{user,csrfToken}`; raw web session token is never JSON. GET `/v1/auth/session` recovers CSRF after page reload, GET `/v1/me` returns the current user. Cookie mutations require Origin and CSRF; login/signup CSRF comes from bootstrap, not a previous account session. The future same-origin web proxy must supply the trusted Origin for bootstrap GET when the browser omits it; integration must account for this rather than letting clients bypass Origin validation.

New/reset passwords have 15–128 Unicode characters, no stripping/rewriting/composition rules; login/deletion candidates have 1–128. Passwords use salted Argon2id (64 MiB, 3 iterations, parallelism 4); each runtime limits expensive hashing to two concurrent operations outside transactions. Unknown email/wrong password share 401 invalid_credentials. Duplicate registration uses 409 registration_conflict, an explicitly accepted enumeration trade-off. Existing IndexedDB email/password digests cannot authenticate a server account. Sessions/tokens are stored as digests; auth responses and errors use no-store. Account requests authenticate only by web cookie; Authorization headers cannot authenticate and are rejected.

Configure all SMTP settings together: HOST/PORT/USERNAME/PASSWORD/FROM/SECURITY, with `smtps` or mandatory `starttls`, certificate verification and 10-second timeout. Secrets stay in the deployment environment. Without SMTP, registration, POST `/v1/auth/verify-email/request` and `/password-reset/request` return 503 email_unavailable uniformly before identity/token writes. Existing-account login/me/session/logout/confirm/deletion can still operate. Production has no fake/console mailer.

SMTP registration commits a pending user and verification token before sending; send failure returns 503 without a session cookie, leaving a recoverable pending account. Use login and resend once delivery recovers; retrying registration returns duplicate conflict. Configured resend/reset-request 204 means request accepted, including unknown email, and never confirms inbox delivery. Delivery failure logs only purpose/category; user may retry after rate-limit cooldown. Mail links target future web `/auth/verify-email` and `/auth/password-reset` pages with token in the URL fragment. These UI pages remain ANY-653; until integrated, an operator can consume a received token through the corresponding POST API. Verification POST additionally requires the matching user's web session and CSRF, preventing an unsolicited link from verifying an attacker's pre-registered account. Reset-confirm takes `{token,password}`, trusted Origin, revokes all sessions/codes and does not log the user in automatically.

Pending accounts may use me/session/resend/logout/delete. Account business operations require verified email. Future profile/job/report/annotation/import services must use `verified_principal` and `load_owned`; the latter filters resource ID plus server-resolved owner and returns 404 for missing/foreign data. DELETE `/v1/me` requires current password in JSON, current session and transport protection; it atomically deletes private account/claimed-guest data and anonymizes provider-call links. Concurrent guest claims cause fresh graph re-enumeration, up to three attempts, then safe 409 ownership_conflict.


Absolute TTL: web 7 days, verify 24 hours, reset 30 minutes, bootstrap 15 minutes. Fixed-window limits are shared in PostgreSQL: login 10/email and 60/IP per15m; register5/IP/hour; verify/reset requests3/email and20/IP/hour; token confirmation30/IP/15m; bootstrap60/IP/15m; delete5/user/15m. Counters include rejected attempts and survive business rollbacks; 429 includes Retry-After. Expired limiter rows are deleted in batches of at most100; general retention scheduling remains future work. HMAC hides raw email/IP in buckets. By default forwarded IP headers are ignored; `FITCHECK_TRUSTED_PROXY_IPS` accepts explicit proxy IP/CIDR only. Inspect the Dokploy proxy network before enabling trust; never use `*`. Without proxy configuration IP budgets aggregate at the proxy while per-email limits still apply.

Unit/integration tests and container smoke use disposable PostgreSQL only. SMTP-adapter tests replace the external SMTP transport, preserving TLS/message/error behavior; real sending requires credentials supplied later. Website auth code in this branch are not a claim that production auth or UI integration has been deployed. Production backups/restore and automated deployment ordering remain ANY-654.

## Durable jobs and worker (ANY-649)

Verified accounts can POST `/v1/analysis-jobs` or `/v1/skill-suggestion-jobs`
with Origin, session CSRF and an `Idempotency-Key` (1–200 characters). Responses
are 202 `{jobId,type,status}`. Same owner/type/key and normalized request replays
the original job, including its current terminal status; changed request returns
409. Explicit new analysis means a new key. GET `/v1/jobs/{jobId}` returns an
owner-scoped state, embedded immutable analysis result on success, or skills.
Foreign/missing jobs return 404. Guest admission and website integration remain
ANY-651/653. API admission/read never waits for or calls a model.

`FITCHECK_JOBS_ENABLED=false` is the safe default. Disable admission during
maintenance; existing GET stays available. Enable only after the separate worker
is healthy. When enabled with an unavailable worker, jobs persist queued.
Admission allows at most two queued/running account jobs across both types;
new requests are limited to 10/user/minute and 60/IP/15 minutes. Duplicates do
not reserve another active slot or consume another rate token.

Run migrations separately before API/worker rollout, then start the worker from
`backend/` with the same database and a worker-only `FITCHECK_DEEPSEEK_API_KEY`:

```sh
uv run --locked python -m fitcheck_backend.storage.migrate upgrade
uv run --locked python -m fitcheck_backend.worker
# Alternatively, with complete backend/.env:
docker compose -f compose.worker.yaml up -d --build
```

Container deployments use `backend/Dockerfile.worker` with context `backend/`.
Worker starts only with a provider key and matching schema; no public worker HTTP
port is needed. It processes one job at a time; multiple processes may scale the
same queue. Defaults: poll 1s, lease 150s, heartbeat 20s, drain 130s. Environment
variables `FITCHECK_WORKER_POLL_INTERVAL`, `LEASE_SECONDS`, `HEARTBEAT_SECONDS`
and `DRAIN_SECONDS` use that common prefix. Set container stop grace to 140s.
`python -m fitcheck_backend.worker.health` checks a fresh live-process marker;
busy jobs refresh it after successful database heartbeat. DB operations have
5s statement/connection/pool timeouts; queue/publication locks have 3s timeout.

Claim uses PostgreSQL SKIP LOCKED. Each execution has a unique lease token;
expired or replaced tokens cannot heartbeat or publish. Result and succeeded
status commit atomically; provider ledger commits independently. Profile,
calibration, edited vacancy and versions are frozen at admission. Unsupported
versions/legacy bare-input jobs fail safely before provider HTTP.

Process loss recovers once (at most two executions). Final ordinary provider
errors fail the job; gateway already bounds its physical/semantic retries.
A crash after a paid response but before result commit may cause another paid
call on recovery. There is no exactly-once provider guarantee. Separate operation
UUIDs/execution tokens preserve repeat costs; unknown usage/cost remains null.
Recovery marks stranded started calls unknown/process_lost and preserves already
recorded successful usage. A late response cannot reverse that reconciliation.

Rollback: disable new admission, drain/stop worker, keep GET and the additive
schema/data. Do not downgrade populated provider token columns or reset a DB.
Paid canary requires explicit opt-in; unit/integration tests use fake provider
responses and disposable PostgreSQL, including claim/publish/recovery races.

## Retention policy

| Data | Retention |
| --- | --- |
| Account profiles/revisions/history | Until account deletion |
| Unclaimed guest data | 30 days after guest expiry |
| Expired/revoked sessions and consumed/expired auth tokens | 7 days after expiry/revocation |
| Terminal jobs and idempotency records | At least 30 days after completion |
| Anonymous provider metrics | 90 days |

Account deletion removes the ownership graph, including claimed guests' remaining private profile/draft data. Ledger owner/job/request-key links are cleared before cascading deletion; only technical metrics survive. Job cleanup must detach optional analysis and ledger links before deleting a referenced job, preserving its report snapshot. Guest history transferred to an account follows account retention. Quota/import deduplication records remain for their policy/account lifetime. Cleanup scheduling, account deletion HTTP flow and configurable TTL enforcement are future service/operations tasks; ANY-644 defines the policy and tests the storage behavior.
