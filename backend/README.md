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

Storage and migrations are implemented in ANY-644, server authentication in ANY-645, profile/preferences/draft API in ANY-646, vacancy extraction in ANY-647 and the LLM gateway/services in ANY-648. Durable jobs ANY-649 and history ANY-650 are implemented. Remaining tasks: guest quotas ANY-651, local import ANY-652, UI integration ANY-653 and production operations ANY-654. Current Next.js APIs and website remain active until integration.

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

From the repository root, `pnpm backend:types` regenerates TypeScript and `pnpm backend:types:check` verifies drift without writing. Generated types live in lib/backend/generated/schema.ts; edit Python DTOs instead. lib/backend/client.ts is a transport factory with mandatory success validation, structured errors, AbortSignal and configurable credentials. Its base URL is /backend/v1 for the future website proxy or a configured API origin ending /v1. Route arguments are relative to that base; external URLs/traversal are rejected. Redirects and automatic mutation retries are disabled. The website uses this transport through the server-only `/api/backend/v1/*` relay; see the ANY-653 rollout record.

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

`OPEN_AI_KEY` is optional for API startup/admission and required in the worker
for provider calls. Python settings use explicit `OPEN_AI_KEY` / `OPEN_AI_MODEL`
aliases without the `FITCHECK_` prefix. Configure exact
`OPEN_AI_MODEL=gpt-6-luna` on both API and worker; unsupported values fail safely.
Missing key returns safe `service_unavailable` before DB/provider work.
Provider/model/prompts are server-owned: active policy uses OpenAI `gpt-6-luna`,
`fitcheck.llm.policy.v2`, `reasoning_effort=none`, JSON-object output and
`max_completion_tokens`; temperature is omitted. The fixed destination is
`https://api.openai.com/v1/chat/completions`.
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
The Python provider boundary suppresses LiteLLM and OpenAI SDK payload logging,
including SDK child loggers enabled by `OPENAI_LOG=debug`. FitCheck operational
request, worker health and failure logs remain enabled; do not log provider
messages, output, raw errors or keys for diagnostics.

Basic skills are not professional strengths. The model selects unique allowed
strength IDs; the server renders text and provenance. Currency comparisons retain
unknown/mismatched currency and minimum-only hourly budget semantics. Fixed budgets
are not compared to hourly rates without effort estimates. Narrative audit checks
profile/task grounding before success. The server returns `verdictThreshold: 70`
and computes GO only at score ≥ 70. Legacy results may omit this new field.

### Conditional verdict (ANY-576)

For a GO score, the generator may propose a short prerequisite for a significant,
explicitly grounded and remediable risk. Its internal `{clause, riskIndex}` points
to an existing risk; invalid references and conditions on NO_GO scores are rejected
before audit. The linked risk is retained when competition takes a risk slot.
The server adds `Suitable if …` / `Подходит, если …` in the report locale and keeps
the existing public `fitCondition` string contract (at most 300 characters).

Grounding audit receives the complete condition, its linked risk, score, verdict,
profile and task. A condition requires explicit `fitConditionSupported=true` in
addition to the usual supported-claims verdict; a missing/false confirmation causes
generation correction, within the existing shared attempt/call budget. The audit
checks significance, feasible remediation, factual grounding and consistency.
Unknown credentials, output-content languages, minor caveats and high competition
alone cannot establish a condition. Prospective client agreement never claims that
agreement already exists. The condition changes neither score nor verdict.

Unconditional and legacy results omit the field; the website shows a saved condition
under GO only with a nonempty risk list. New/history/demo reports use the same view.
No database migration or new environment setting is needed. Historical results remain
unchanged until explicit reanalysis creates a new report.

### Competition evidence (ANY-575)

Analysis uses explicit `proposalCount`, `averageBid` and `averageBidCurrency`, with
conservative extraction from labelled description statistics for manually pasted
tasks. Reviewed structured fields take precedence. English/Russian labels and
adjacent label/value lines are supported; conflicting or ambiguous numbers are
omitted. Average bids never become task budgets, and a bid's currency is never
borrowed from the budget or a different quote.

Competition bands are qualitative product heuristics: 0–9 proposals is low,
10–49 medium, 50+ high. Single-digit, tens and many dozens of competing proposals
separate small pools from substantial proposal effort; these bands are not
empirical hiring probabilities. The model considers competition in attractiveness
and recommendation; there are no fixed numeric score deductions. Unknown counts
remain unknown, never zero/low, and missing statistics do not lower the score.
An average bid is context, not proof of an accepted price or a comparable hourly
rate: payment units are not established by these fields.

The server keeps known statistics in the explanation and reserves the first risk
for medium/high competition, including when the model omits it or returns three
other risks. RU/EN reports retain the existing 800-character summary and three
240-character risk limits. Grounding audit sees the same resolved statistics and
the final report. Public DTOs and stored snapshot schemas are unchanged.

Analysis generation/audit prompts are now `fitcheck.analysis.prompt.v3` and
`fitcheck.analysis.audit.v3`. As with other frozen-version changes, drain active
jobs with the old worker before replacing API/worker together; old prompt-version
jobs are rejected rather than silently executed with different instructions.
Historical results remain unchanged; explicit reanalysis uses the new behavior.

Additive migration `0002` extends `provider_calls` with prompt/schema/policy versions,
semantic/transport indices and latency_ms. Apply it before restarting the upgraded
API/worker; existing initial `0001` and payloads remain valid. Generation and audit
record their respective schema versions. Start rows are separately committed before
network I/O; final metrics survive operation failures and do not hold a DB connection
during requests. Ledger failures stop the operation. Validation failures retain usage
while marking the call failed; a failure to finish a row leaves `started` for future
reconciliation. Unknown tokens/cost remain null. Historical costs retain available SDK estimates. New OpenAI text costs use the
versioned Standard/global rate snapshot described below; no raw requests/responses, secrets or personal content
are persisted in ledger or SDK telemetry.

Deterministic mock/HTTP-transport tests use the real PydanticAI/LiteLLM adapters.
Optional paid canary, from `backend/`, requires a concrete approved spend cap, an explicitly supplied key and opt-in:
`FITCHECK_RUN_LLM_CANARY=1 uv run --locked pytest tests/analysis/test_live_canary.py -q`.
It uses only anonymized fixtures and in-process metrics; PostgreSQL accounting is
tested separately on disposable PG. Without opt-in/key it is reported as skipped.
For real API admission → WorkerRuntime → persisted results and physical-attempt
accounting, supply `FITCHECK_TEST_DATABASE_URL` for disposable PostgreSQL and run:
`FITCHECK_RUN_LLM_CANARY=1 uv run --locked pytest tests/integration/test_live_llm_jobs.py -m integration -q`.
This paid canary uses anonymized fixtures and the supplied `OPEN_AI_KEY`; default
job exposure limits are $0.02 for analysis and $0.005 for suggestions. It checks
both successful results and equality of HTTP sends and durable ledger rows.
Library behavior references: [PydanticAI output](https://pydantic.dev/docs/ai/core-concepts/output/),
[LiteLLM SDK](https://docs.litellm.ai/docs/python_sdk).

## Verification and rollout

CI runs backend pytest and OpenAPI drift with Python 3.12/uv 0.12.7, plus generated TypeScript drift and the existing frontend test/typecheck/lint and website builds. For a fresh Node install run `pnpm install --frozen-lockfile`; `pnpm exec next typegen` generates Next route declarations when needed.

Storage and authentication are implemented separately from the remaining business/LLM routes. A persistent development database was provisioned separately at the user's request on 2026-10-12; see the deployment record below. The ANY-653 web proxy `/api/backend/v1/*` connects implemented API operations; old public LLM/extraction routes return 410. ANY-654 still covers production operations, worker deployment, automated migration ordering and backup/restore validation.

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

SMTP registration commits a pending user and verification token before sending; send failure returns 503 without a session cookie, leaving a recoverable pending account. Use login and resend once delivery recovers; retrying registration returns duplicate conflict. Configured resend/reset-request 204 means request accepted, including unknown email, and never confirms inbox delivery. Delivery failure logs only purpose/category; user may retry after rate-limit cooldown. Mail links target future web `/auth/verify-email` and `/auth/password-reset` pages with token in the URL fragment. The website implements these UI pages in ANY-653, with code entry/resend and fragment removal after reading. Verification POST additionally requires the matching user's web session and CSRF, preventing an unsolicited link from verifying an attacker's pre-registered account. Reset-confirm takes `{token,password}`, trusted Origin, revokes all sessions/codes and does not log the user in automatically.

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
`backend/` with the same database, exact `OPEN_AI_MODEL=gpt-6-luna` on API
and worker, and server-only `OPEN_AI_KEY` in the worker secret store:

```sh
uv run --locked python -m fitcheck_backend.storage.migrate upgrade
uv run --locked python -m fitcheck_backend.worker
# Alternatively, with complete backend/.env:
docker compose -f compose.worker.yaml up -d --build
```

Container deployments use `backend/Dockerfile.worker` with context `backend/`.
The local CLI handles Ctrl+C with graceful shutdown on Windows as well as POSIX.
When the event loop cannot register signals, it uses Python signal handlers to
schedule the same drain; prior handlers are restored when the worker exits.
Worker starts only with a provider key and matching schema; no public worker HTTP
port is needed. It processes one job at a time; multiple processes may scale the
same queue. Defaults: poll 1s, lease 150s, heartbeat 20s, drain 130s. Environment
variables `FITCHECK_WORKER_POLL_INTERVAL`, `LEASE_SECONDS`, `HEARTBEAT_SECONDS`
and `DRAIN_SECONDS` use that common prefix. Set container stop grace to 140s.
`python -m fitcheck_backend.worker.health` checks a fresh live-process marker.
Windows probes, heartbeat updates and shutdown cleanup share a path-specific
named mutex. File handles close before the next operation, preventing replacement
and deletion races; waits are bounded and abandoned locks are recoverable.
After a reader crashes, Windows can release its mutex before closing its file
handles. Marker replacement/deletion retries sharing errors for at most 255 ms.
If contention or another health I/O error persists, the worker logs a warning and continues; it does not
refresh the old timestamp, so health expires until a later update succeeds.
Health I/O runs outside the event loop so a stalled probe cannot block signals
or database heartbeats. Shutdown closes provider/database resources independently
of marker cleanup, and prevents late background writes from recreating the marker.
Each local worker needs a distinct `FITCHECK_WORKER_HEALTH_PATH`. A nonblocking
OS lock on the adjacent `.owner` file rejects a second worker using the same path.
The guard file intentionally remains after shutdown; its OS lock is released on
normal exit or process death. Do not remove it while a worker is running.
An invalid/unwritable health directory rejects startup; runtime monitoring failures
degrade health until storage recovers rather than stopping queue processing.
On Windows it inspects a process handle with a nonblocking Win32 wait, without
calling `os.kill` or sending console signals. Windows CI runs the original health
tests and CLI shutdown tests on Python 3.12 and 3.14.
Busy jobs refresh it after successful database heartbeat. DB operations have
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

The [OpenAI rollout record](../docs/deployments/2026-10-14-fitcheck-openai.md)
defines the ordered drain, 0007 migration, API registry, compatible worker,
admission and website transition. Disable all three autodeploy switches before
pushing provider changes; restore them only after controlled rollout evidence.
Old DeepSeek job envelopes and ledger records remain immutable. Never send an
old frozen job through the new OpenAI registry.

Before migration, disable admission on the existing API using Dokploy **Reload**
with its pinned pre-migration runtime/image retained; verify the same SHA/image
afterward. Do not rebuild the newly pushed branch to apply this environment change.
If the drain fails before 0007, abort the switch and retain the old matching
runtime, worker and key against its unchanged schema.

After 0007, direct backend rollback to the old exact-head-0006 API/worker images
is unavailable: the API readiness and worker startup schema gates reject 0007.
Keep admission off and retain or start the reviewed current 0007-compatible
runtime, then repair forward. A provider rollback requires a separately reviewed
artifact supporting both schema 0007 and the intended frozen provider versions;
none is prepared by this migration. Drain incompatible work with its matching
worker/key before any fleet transition. Preserve GET on a schema-compatible API,
0007, domain/telemetry rows, envelopes and costs. Recovery is less immediate and
job admission can remain unavailable during repair. Never bypass schema checks,
downgrade/reset the DB, delete jobs or rewrite frozen work to make old images boot.
Paid canary requires a concrete approved spend cap and explicit opt-in; unit/integration tests use fake provider
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

## Telemetry and operator reports

Telemetry uses additive migrations `0004_metrics`, `0005_metrics_erasure`, and
`0006_metrics_coverage`. OpenAI accounting adds `0007_provider_usage_basis`;
frozen `0001`–`0006` must not be rewritten. Apply the matching schema head
before enabling the upgraded API and worker. Historical DeepSeek costs stay unchanged.
See the [development rollout record](../docs/deployments/2026-10-14-fitcheck-metrics.md)
for ordering, evidence, approved decisions and remaining live checks.

Enable `FITCHECK_METRICS_ENABLED=true`, explicit
`FITCHECK_METRICS_ENVIRONMENT=development`, and `FITCHECK_METRICS_INGEST_KEY` in the
API and worker's supported secret/configuration store. The website uses the matching
`METRICS_BRIDGE_KEY`, fixed HTTPS `METRICS_BACKEND_URL`, separate high-entropy
`METRICS_COOKIE_SECRET`, and matching `METRICS_ENVIRONMENT`. These environment
partitions are independent of `FITCHECK_ENV=dev` and production `NODE_ENV` builds.
Never use provider keys as telemetry secrets. Templates contain no real credentials.

Set `FITCHECK_METRICS_DATABASE_ENVIRONMENT=development` independently: it asserts the
physical database scope for legacy domain/provider records and backfill, which lack
per-row environment. Do not change it during temporary `test` ingestion. Without a
matching explicit database scope, legacy metrics are unavailable; scoped journal
observations remain reportable. Mixed historical database environments need future
reconciliation. Mirror public campaign codes as backend JSON array (for example
`["launch"]`) and website comma-separated `METRICS_CAMPAIGN_CODES=launch`; unknown
values map to `other`, absent values to `direct`. Website enabled/campaign props are
prerendered and require configuration at build time plus rebuild/deploy on changes.

Reports are operator CLI only, with database access; there is no public report API.
From `backend/` with explicitly exported settings (dotenv is not automatically read):

```sh
uv run --locked python -m fitcheck_backend.metrics --help
uv run --locked python -m fitcheck_backend.metrics report \
  --start 2026-10-01T00:00:00+03:00 --end 2026-10-14T00:00:00+03:00 \
  --timezone Europe/Moscow --environment development --population all \
  --format json --output /tmp/fitcheck-metrics.json
uv run --locked python -m fitcheck_backend.metrics report \
  --start 2026-10-01T00:00:00+03:00 --end 2026-10-14T00:00:00+03:00 \
  --timezone Europe/Moscow --environment development --population visitor \
  --format csv --output /tmp/fitcheck-metrics.csv
uv run --locked python -m fitcheck_backend.metrics backfill --environment development --limit 1000
uv run --locked python -m fitcheck_backend.metrics cleanup --dry-run --limit 1000
# Mutating cleanup, after reviewing dry-run output:
uv run --locked python -m fitcheck_backend.metrics cleanup --execute --limit 1000
```

In an installed operator container replace `uv run --locked python` with
`/app/.venv/bin/python`; ensure that container contains the target committed code.
Backfill mutates telemetry only, requires matching independent database scope, and
repeats bounded idempotent batches; it never invents views, queue claims or activity.
Each drain fixes an exclusive `backfill_target_at` and returns
`backfill_complete`, `backfill_complete_through`, and the outstanding target.
Repeat until complete; a processed count alone is not completion evidence. A new
invocation after completion starts a later cutoff. Reports requiring reconstructed
facts remain unavailable unless their end is at or before the last completed
cutoff, even when registration rows have already been inserted. The completion
watermark proves all eligible persisted facts in the drain's repeatable-read
snapshot, including existing live facts; it does not promise future late writes.
Concurrent maintenance fails safely; retry after the other command finishes.
Cleanup advances an independent monotonic retention floor. Old late events or
subsequent backfill never lower that floor or silently restore removed history.
Existing 0005 collection boundaries are preserved conservatively on upgrade and
reconstruction completeness starts unknown until a completed drain.

Backend registration cohorts retain their registration source. Exact verification,
profile and completed-analysis outcomes for those same backend accounts can come
from either backend source; coverage lists the outcome sources explicitly. Cohort conversions also respect the
latest retention floor across both backend sources, so deletion of live outcomes
cannot become zero in a reconstructed registration cohort. This
never joins website visitors or reconstructs viewed activation or observed returns.

Maintenance limits are 1–1000, default 1000. Cleanup defaults to dry run even without
`--dry-run`. It has no scope filter: do not use it to erase a named synthetic scope.

Report dates require explicit offsets and a positive half-open `[start,end)` UTC
range of at most 366 days with no future end. Timezone defaults to Europe/Moscow;
`--population` is required (`visitor`, `account`, or `all`) and never merges people
across populations. JSON and CSV contain aggregate rows, dimensions, value,
numerator/denominator, sample count, coverage, availability/reason and data start,
with no subject/call/operation/result identifiers. CSV preserves nulls and escapes
formula-leading cells. A repeatable-read read-only snapshot uses 5-second statement,
1-second lock, and 10-second idle transaction timeouts. Projections cap each query
at 100,000 rows and fail explicitly; narrow the period instead of treating failure
as a zero. Context before period start is bounded to 180 days.

### Metric interpretation

| Metric | Implemented basis |
| --- | --- |
| Activation | 100 × subjects activated within seven days of registration / registrations whose full seven-day window ends by report end. Website activation is a viewed analysis result; backend activation is successful analysis completion. |
| Onboarding / email verification | Same mature registration denominator, with profile save / verified email within seven days. Email verification is backend only. |
| Time to value | Seconds registration → first qualifying activation, p50/p95 among the activated mature cohort. |
| Funnel | Ordered first page view → local registration → profile save → analysis request → result view within seven days; each stage / mature first-entry cohort × 100. |
| Active subjects / stickiness | Distinct useful-action subjects in trailing 1/7/30 days ending at report end; stickiness = 100 × DAU / MAU. Page views, login and retries alone are not useful actions. |
| D7 / D30 retention | Useful return during local calendar day [7,8) / [30,31) after first observed activation; full return window must be mature. Observed registration and retained registration-to-activation history required; uncertain first activations are excluded with coverage counts. |
| Feature adoption | 100 × active subjects using the feature / all useful-action active subjects in period. |
| Sessions | Observed starts among active visitors / active visitors; median duration sums visible activity pulses capped at 30 seconds each, not wall-clock tab duration. |
| Acquisition | First observed retained page-touch campaign counts for period visitors, registrations and activations, not arbitrary URL attribution or authenticated account linking. |
| Feedback coverage | 100 × mature successful website analyses with linked feedback within seven days / mature successful analyses; same visitor and server operation ID required. Legacy unlinked history excluded. |
| Score correction | Median absolute predicted-minus-corrected score and bucket counts from latest period feedback per result; not model accuracy or a satisfaction survey. |
| Operations | One logical operation, distinct from physical generation/audit/retry calls. Success rate = 100 × successes / terminal operations finishing in period. Latencies p50/p95 use available timestamps; website creation is reconstructed only from non-clamped terminal duration. |
| Provider coverage / spend | Calls started in period; terminal/known-cost coverage reports percentages with counts. Known spend sums only priced calls, separately per currency, date/provider/model/purpose/outcome/cost basis. Unknown token fields or costs stay null, never inferred as zero. |
| Cost per success | Known spend across all observed attempts through report end for operations created in period / successful operations in that cohort, per currency. Failed attempts and audits contribute spend, not extra successes. Attempts per operation uses the same cohort. |

Ratios with empty denominators and empty percentile samples are null. Percentiles
use nearest rank (`ceil(n × percentile/100)`). Read coverage alongside every value:
collection start, retention floor and incomplete delivery can make a metric
unavailable. Observed and reconstructed backend provenance stays separate;
reconstructed history cannot establish viewed-result retention. Website operation
starts and missing terminal facts are not authoritative: pending state and creation
cohort completeness are unavailable even if all observed calls have terminal facts.
Known cost-success ratios cover observed operations with reconstructable creation;
unlinked calls and unresolved operation counts disclose missing coverage.

No MRR/ARR, payment conversion, subscription churn, NRR/GRR, CAC/LTV, margin, sales,
NPS/CSAT/CES or historical outcome conversion source exists. Rows state specific
unavailability reasons. Corrected scores are not surveys. Backend application
statuses are current snapshots, not historical transitions. Backend feedback is stored by ANY-650 and participates in server calibration;
feedback journal/report integration and website account/backend identity linkage
remain separate integration work.

### Collection, deletion and retention

The registry accepts bounded technical facts, no account emails/passwords, profile
or vacancy text, full URLs, raw UTM, IP identity, prompts or responses. Website
visitor IDs are signed-cookie identities, independent of local IndexedDB accounts
and backend accounts; shared browsers and multiple devices cannot establish people.
The HttpOnly cookie has a hard 180-day issuance expiry without sliding renewal.
Deletion rotates visitor/session identity, requests erasure of that visitor's facts,
and detaches provider accounting. Remote failure means erasure delivery is not
proven; the product flow continues. Backend account deletion removes associated
facts atomically and retains only anonymous deletion counts and detached accounting.
Erased visitor digests fence late facts for 181 days without retaining raw identity.

Browser queues are in-memory, max 100 events, 20 per batch, 32 KiB, two retries.
Bridge delivery has a 1500 ms deadline and refuses redirects. Collector limits are
60 requests per minute per trusted bridge environment. Client clock skew over five
minutes is adjusted to receipt time. Blockers, closure, restarts and failed delivery
lose observations; process-local diagnostic counters cannot measure all losses.
Unknown spend and delivery coverage remain unknown, including failed final delivery.

Cleanup removes journal facts older than 180 days by **received_at**, advances
available-history metadata, and removes expired 181-day erasure digests in bounded
batches. It preserves domain data and provider/website accounting ledgers; ledger
retention follows its separate policy and is not implemented by this cleanup.
No scheduler is installed by these commands. Reports expose availability floors;
a 366-day selectable range does not promise 366 days of raw events.

Disable collection by setting API/worker `FITCHECK_METRICS_ENABLED=false`, removing
website bridge configuration and rebuilding/redeploying its static enabled props.
Preserve migrations, domain data and accounting ledgers. Stop any operator cleanup
schedule separately. Do not downgrade/reset the database as telemetry rollback.


OpenAI token costs use `openai.luna.2026-10-16`, verified against the official
[pricing](https://developers.openai.com/api/docs/pricing) and
[Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna) pages on
2026-10-16: USD per million text tokens is 0.10 input, 0.01 cached input,
0.125 cache writes and 0.50 output. Cached and written tokens are subdivisions
of total input; completion tokens already include reasoning. The estimate uses
integer nano-USD arithmetic; both ledgers store `NUMERIC(24,12)`, the website
DTO accepts 12 decimal places and report JSON emits Decimal values as strings.
A single cache-write token therefore stays exactly `0.000000125` USD.

Only a known actual Standard tier (`default`), global processing and at most
272,000 input text tokens are priced. Missing cache read/write counts or usage,
invalid subdivisions, unsupported models/rate versions/tiers/regions and long
context remain unpriced with an explicit reason. The response's actual tier
can differ from the request. A missing count never means zero. Rate version,
actual response model/tier, region and unknown reason remain optional accounting
metadata; report spend groups include rate version/tier/region and reason.
Old SDK costs remain `estimated` with no fabricated rate version, including
historical DeepSeek rows. Neither estimate source is an invoice verification.
Known spend and coverage retain failed generations, audit calls and retries;
cost per success divides all observed cohort attempts by operation successes.
Migration 0007 refuses a rollback if narrowing costs to eight decimal places
would lose data.

## History API (ANY-650)

Verified website accounts can read `GET /v1/history` and
`GET /v1/analyses/{analysisId}`. History accepts `limit` (1–100, default 20),
`verdict=GO|NO_GO`, `applicationStatus`, `sort=newest|oldest` (default newest),
and an opaque `cursor`. Ordering is `(createdAt, analysisId)` in the selected
direction. Signed cursors bind the owner, filters and order; changing those
requires starting a new page sequence. The page size may change. Keyset paging
works even if the boundary record is deleted. It is a live view: later inserts
before the cursor are seen on refresh; changing filters/status during traversal
requires refresh for a complete current view.

Details and history include the original vacancy/optional URL, immutable profile
snapshot/revision, result/date, nullable feedback and application status.
`currentProfileRevision` and `profileChanged` compare the stored backend revision
with the current one. `profileChanged=null` means no comparable revision exists
(for example a transferred guest or legacy import); it is never guessed from a
legacy revision string. Job polling uses the same resource representation.

Cookie mutations require trusted Origin and CSRF:

- `PUT /v1/analyses/{analysisId}/feedback`: `{ "correctedScore": 60, "note": "..." }`;
  score is an integer 0–100, note is optional and at most 500 characters.
  Send JSON `null` to clear feedback; an absent body is invalid.
- `PUT /v1/analyses/{analysisId}/application-status`: `{ "applicationStatus": "applied" }`.
  Allowed statuses are `not_applied`, `applied`, `replied`, `interview`, `rejected`,
  `hired`. Users may correct any status to any other status, including reset.
  Updating status preserves feedback and vice versa.
- `POST /v1/analyses/{analysisId}/reanalyses`: requires `Idempotency-Key` and enabled
  jobs. Returns 202 `{ "jobId": "..." }`. Atomically freezes the original vacancy
  and locale with the current profile/revision and server calibration memory into
  a new durable job; completion adds a new result and preserves the previous one.
  A retry of the same key/source returns the same job even after profile changes;
  use a new key for another attempt. Reusing the key for another source or ordinary
  analysis conflicts. Existing admission rate/concurrency limits apply.
- `DELETE /v1/history`: removes the owner's completed results, annotations and
  unreferenced stored vacancies. Profile/revisions, active jobs and technical
  accounting/admission records remain. A job completing after the clear can add a
  new result. Deleted analysis detail and its completed job result return 404;
  replaying an admission key cannot recreate an erased result.

Feedback enters calibration memory for subsequent admissions; previously queued
jobs retain their frozen memory. Requests recheck the active verified session
inside the transaction. Mutations serialize with account deletion, profile
updates and admissions; another owner's resource returns 404. Existing tables
support this API, so no new database migration is needed. Website UI integration
remains ANY-653 and related product tasks ANY-577/578/580.

## Guest sessions and quotas (ANY-651)

Guest admission is disabled by default (`FITCHECK_GUEST_ENABLED=false`). Enable
only after migration 0008 and matching API/worker rollout. Obtain the existing
`GET /v1/auth/csrf` bootstrap, then `POST /v1/guest-sessions` with trusted Origin
and `X-CSRF-Token`. The response returns guest `csrfToken`, absolute `expiresAt`
and `demoLimit`; the opaque cookie is Secure/HttpOnly/SameSite=Lax in production.
Reusing a live cookie preserves its expiry and credits. Issuance permits 3/IP/hour
and 10/IP/day; deleting cookies does not clear those rate attempts.

`POST /v1/analysis-jobs` selects the identity explicitly with body `mode`.
Guest bodies include `profile`, `vacancy`, `locale`; accounts use the existing
`profileRevision`. Extractions, skill suggestions, quota, job polling and analysis
detail accept `?mode=guest|account`. Without a selector, an account cookie takes
precedence. An invalid selected cookie fails; there is no fallback. Bearer access
is rejected. Mutations need the selected session's CSRF and trusted Origin.
History, feedback, application status and reanalysis remain verified account-only.

`GET /v1/quota` reports analysis `remaining`/`resetsAt`, `mode`, guest `expiresAt`,
`registrationRequired`, active-job counts, and per-operation
`limit`/`remaining`/`reserved`/`consumed`. Guest limits per absolute 24-hour session
are 1 successful analysis, 5 suggestions and 10 extractions, with 1 active job.
Verified accounts get 20 analyses (including reanalysis), 50 suggestions and
100 extractions per UTC day, with 2 active jobs. A job reserves credit atomically;
success consumes it and terminal failure releases it once. Lease retries and
same-key replay use the original reservation. Extraction reserves a 120-second
lease around network work; late success cannot consume an expired lease.
Guest jobs allow 5/guest/minute and 30/IP/15 minutes; extraction allows
10/guest/minute and 60/IP/15 minutes. Failed operations still count rate attempts.

Technical limits are separate from successful-operation credits. Every physical
provider send, including audit and retries across worker leases, reserves durable
call/token/USD exposure before sending. Defaults: analysis 8 calls, 40,000 total
tokens, $0.02/job; suggestions 4 calls, 10,000 tokens, $0.005/job; guest lifetime
$0.05, account UTC-day $0.50, deployment UTC-day $10. Values are configurable in
`backend/.env.example`. New jobs freeze their job limits; existing v1 jobs retain
compatibility and snapshot safe defaults on their first call without retroactive
product charges. UTF-8 byte/framing bounds and worst supported cache-write input
pricing deliberately over-reserve. Confirmed supported usage releases proven
excess; missing usage, cancellation, crash and unknown pricing retain exposure.
Known usage accounting remains independent of this conservative ceiling.
`quota_exceeded` and `budget_exceeded` use safe 429 admission envelopes; a running
job reports a typed terminal error. No provider details or SQL enter that envelope.

`POST /v1/guest-claims` requires a verified account, active guest cookie, trusted
Origin, account `X-CSRF-Token`, guest `X-Guest-CSRF-Token`, and `Idempotency-Key`.
Send no body or `{}`. It atomically transfers terminal results/jobs and copies
the latest guest profile only if the account has no profile. Existing account
profile/preferences/draft and immutable result snapshots remain unchanged.
Same account/key/guest replays the stored `{claimedCount, profileImported}`;
a changed guest for the same key, already claimed guest, active job/extraction,
or conflicting job idempotency key returns 409 with no partial transfer.
After claim, guest access is available only for receipt replay until expiry.
Claim never grants account credits or transfers guest spending windows. Account
deletion removes personal links while retaining anonymous deployment exposure.

See [the rollout record](../docs/deployments/2026-10-17-any-651-guest-quotas.md).
Website integration remains ANY-579/ANY-653.
