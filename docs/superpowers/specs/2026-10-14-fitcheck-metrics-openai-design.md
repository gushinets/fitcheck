# FitCheck metrics collection and OpenAI migration

Date: 2026-10-14. Status: proposed written specification for review.

## Purpose and approved scope

Collect the metrics that FitCheck can substantiate now, including current website
usage, and switch its active model provider to OpenAI GPT-6 Luna. The user approved
PostgreSQL event storage, a period report with CSV export, website and backend
instrumentation, and deployment before returning to the existing backlog.
The user explicitly selected the API model ID `gpt-6-luna`.

This work does not implement subscriptions, marketing expense bookkeeping, a CRM,
or the full website integration in ANY-653. Metrics for unavailable functionality
must be reported as unavailable rather than zero or inferred activity. It adds no
new NPS/CES surveys or application-status interface. It instruments existing
feedback and prepares reporting for server application statuses when ANY-650
implements their mutation API.

Success means current website events and provider calls reach the same database
used for backend metrics; reports distinguish identity and data provenance;
transport changes preserve analysis and suggestion output contracts; deployed
website and worker use the selected OpenAI model without exposing credentials.

## Current state

The website uses IndexedDB accounts, profiles and history, synchronous Next.js
analysis and suggestion routes, and direct DeepSeek calls. A local account is not
a verified backend account. The website currently has no application-status flow.
The Python backend has real authentication, profile revisions, durable jobs,
immutable results and provider-call accounting. The worker has leases, heartbeat,
two bounded executions and fenced publication. The website is not yet a client of
these product APIs. Installing backend telemetry alone would therefore miss the
website's current usage and AI expenses.

The deployed services in this session are `fitcheck` website, `fitcheck-api-dev`
and `fitcheck-worker-dev` in Dokploy's `development` environment. They run
production builds. References to deployment in this specification mean these
existing services, not an undiscovered separate production environment.

## Collection architecture

Use PostgreSQL for a versioned event journal and website provider-attempt ledger.
Use the existing backend provider ledger for worker calls. No Redis, external
analytics vendor or new public dashboard is required. The first reporting
interface is an operator CLI with JSON and CSV formats; aggregate reports contain
no subject identifiers or user content.

The website browser posts typed event batches to a same-origin Next.js route.
That route assigns or validates a random signed visitor cookie, stamps receipt
time and forwards to a fixed backend internal collection endpoint. Its bridge
credential remains server-only. The collector must not accept this credential
through a URL, expose it to a public-prefixed variable or forward to a caller's
chosen destination. The internal endpoint verifies the credential, validates
each event against the registry and enforces body, batch and request limits.
Use HTTPS for the deployed bridge and an explicit loopback exception in local
development. Compare shared secrets in constant time.

Browser events are untrusted observations, even when forwarded by the website.
They cannot declare a verified account, a successful provider call, its usage or
cost, or a completed backend job. Trusted website server instrumentation records
its own operation starts, terminal results and each physical provider attempt.
Backend lifecycle events take owner identity from the authenticated principal
or persisted domain record, never from the posted event body.

Browser reporting is nonblocking. Keep a bounded in-memory queue of at most 100
events; batches contain at most 20 events and 32 KiB. Flush after interaction and
on visibility changes, retry at most twice, and do not persist event buffers or
user content. A collector outage must not turn a successful analysis into an
error. Website server delivery also has a short independent timeout and no
unbounded retry; count safe delivery failures so report completeness is visible.
Registration and other backend mutations write authoritative lifecycle events in
the same short transaction as their domain change. Failure observations that
have no committed domain mutation are separate best-effort writes.

## Event and identity contract

Each journal row has event ID, event name and schema version, occurred time,
server received time, deployment environment, source, subject kind and subject
identifier, optional session/operation IDs and allowlisted properties.
Sources are `website_client`, `website_server`, `backend_server` and
`reconstructed_backend`. Environments are explicit `development`, `production`
or `test`, independent of the application's runtime build mode. Default reports
exclude test data and never combine deployment environments silently.

Event ID deduplicates transport retries. Authoritative events also have a unique
source/domain transition key, so admission retries and duplicate job polling
cannot become new activations. Conflicting duplicate IDs are rejected. Client
times must be within five minutes of receipt; use receipt time otherwise and
mark adjustment. Stored timestamps are UTC; report dates use an explicit IANA
timezone, default Europe/Moscow. Time ranges are half-open.

Website visitor identity lasts across sessions while its cookie survives.
Session ID renews after 30 minutes without observed activity. Local registration
uses the visitor subject and a `local_account` event, not an email, password or
local database account ID. Backend accounts have a separate account subject.
Cross-identity linking requires a subsequently authenticated server operation
under ANY-653. Reports never sum distinct visitors and accounts as distinct
people or promise cross-device identity. Clearing cookies creates a new visitor.

Properties must never contain names, emails, credentials, raw IP addresses,
profile or vacancy text, prompts, outputs, feedback notes, arbitrary URLs,
query strings or fragments. Allowed dimensions include locale, known source
platform, URL/text input mode, feature, safe error code, model, provider and
version. Acquisition uses a fixed allowlist of named campaign codes configured
server-side; unknown UTM values map to `other`, missing values to `direct`.
Keep first-touch campaign dimensions immutable for a visitor; report other
attribution methods only if explicitly implemented later.
Allowlisted numeric properties additionally include predicted/corrected score,
bounded active milliseconds and known duration/usage fields. Opaque result IDs
may correlate result views and feedback; they grant no access to product records.

Keep raw events for 180 days with a bounded operator cleanup command. Deleting a
backend account removes its identifiable event associations. Deleting local data
must rotate the visitor cookie and request deletion of that visitor's journal;
do not pretend it also deletes an independently authenticated backend account.
Existing nonidentifying provider accounting follows its current deletion rules.

## Event registry and available instrumentation

Client observations: `page_viewed`, `session_started`, `visible_activity`,
`local_registration_completed`, `local_login_completed`, `profile_saved`,
`vacancy_input_started`, `extraction_requested`, `analysis_requested`,
`analysis_result_viewed`, `skills_requested`, `skills_accepted`, `history_viewed`,
`feedback_saved`, `history_cleared` and `local_account_deleted`.
Emit events after successful local mutations, not before them. Result viewing
deduplicates by subject/result ID and visit; repeated history views are activity
but do not create another first activation.

Website server facts: `extraction_finished`, `analysis_finished`,
`suggestions_finished`, each with bounded outcome/error, duration and operation
ID. Both generation and grounding audit use the same parent operation ID and
separate provider-attempt IDs. Success requires the existing domain validation
and grounding checks, not merely HTTP 200 from OpenAI.

Backend facts: `account_registered`, `email_verified`, `profile_revision_saved`,
`job_admitted`, `job_execution_started`, `job_execution_recovered`,
`job_finished`, `account_deleted`. Existing record timestamps support a one-time
idempotent backfill where the fact is unambiguous; reconstructed data is labeled
and cannot invent page views, first job claims, viewed results or past sessions.
Job sweeps, heartbeat and idempotent admission returns are not user activity.

Feedback and application-status reporting uses implemented event sources only.
Future backend `feedback_saved` and `application_status_changed` events must be
added in ANY-650; do not expose its currently planned mutation routes here.

## Metric definitions

Every value includes period, timezone, environment, population, provenance,
numerator/denominator or sample count, availability and coverage. Division by
zero and empty percentile samples return null, never a fabricated zero. Use
nearest-rank p50 and p95 consistently. Do not apply generic SaaS benchmark targets.

| Metric | Definition |
| --- | --- |
| Registrations | Distinct committed backend registrations; local registrations reported separately |
| Email verification | Registered account cohort verified within seven days / accounts with a complete seven-day observation window |
| Onboarding | Local registrations with first saved profile within seven days / mature local registration cohort; backend analogue separate |
| Website funnel | Distinct visitor cohorts entering through page view during the report period, then ordered local registration, profile, analysis request and result view within seven days; use mature entry cohorts and show each step's numerator and denominator |
| Website activation | Local registrants who view their first successful result within seven days / mature local registrants |
| Backend activation | Account registrants with first succeeded analysis within seven days / mature account cohort; explicitly called completion-based, not viewed activation |
| Time to Value | p50/p95 registration-to-first-view for website; registration-to-first-success for backend; activated users only, activation rate displayed alongside |
| DAU / WAU / MAU | Unique subjects doing a useful action in rolling 1/7/30 days ending at report end; visitors and accounts separate |
| Useful action | Save a profile, finish a user-requested analysis or suggestion, view a result/history, accept a suggestion or save feedback; page views, logins and automatic retries excluded |
| Stickiness | DAU / MAU for the same population and end instant |
| D7 / D30 retention | First-activation cohorts returning to a useful action in day offsets [7,8) and [30,31), using report-zone calendar days; only fully observed cohorts |
| Feature adoption | Active subjects using each named feature / active subjects during the same period |
| Session frequency | Observed sessions / active website visitors, with coverage reported |
| Session duration | p50 observed foreground active time; 30-second visible/activity pulses, count at most 30 seconds per pulse, no idle/background time; explicitly not exact wall-clock duration |
| Acquisition | Visitors, local registrations and activations by first-touch allowlisted campaign; backend account attribution unavailable until authenticated linking |
| Usage intensity | Successful analyses and suggestion operations per active subject; operation IDs deduplicate retries |
| Feedback coverage | Distinct analyses receiving feedback within seven days / successful analyses in the same creation cohort with a complete seven-day observation window |
| Score correction | p50 absolute predicted/corrected score difference and distribution on feedback samples; not model accuracy |
| Outcomes | Current counts by application status when available; conversion requires recorded transitions and mature cohorts, cannot infer transitions from a final status |
| Reliability | Terminal successful operations / terminal operations grouped by source/type; queued/running counted separately; safe error distribution |
| End-to-end latency | p50/p95 terminal timestamp minus admission/request timestamp; provider and queue/execution durations separately when recorded |
| Recovery and retries | Jobs with multiple execution tokens, physical provider attempts per operation, recovered and exhausted jobs; polling is not an attempt |
| AI usage and costs | Tokens and known/estimated spend by date, source, provider/model, operation and outcome; cost per successful operation includes failed and repeated calls in its cohort |

Cost-per-success cohorts use operations created in the selected period, all their
observed attempts through report end, and successes completed by report end.
Report pending operation counts alongside the denominator. Date-based spend uses
attempt start time and must not be confused with this operation-cohort ratio.

When outcome functionality, cohorts or identity linking are unavailable, return
an explicit reason and collection start date. Show website observation metrics
separately from authoritative backend facts. Client blockers and failed delivery
can reduce coverage; do not represent website observations as exhaustive.

MRR/ARR, paid conversion, subscription churn, NRR/GRR, CAC/LTV, margins and sales
metrics remain unavailable with specific missing-source reasons. No billing or
financial values are simulated. NPS, CSAT and CES require actual survey responses
and are unavailable in this scope; corrected score is not a CSAT response.

## Provider attempt accounting and cost coverage

Website attempts store a generated unique call ID, parent operation ID, visitor
and environment, model/provider, prompt/policy versions, attempt indices,
started/finished times, safe state/error and optional usage/cost metadata.
Never store prompts, responses or credentials in telemetry. Start/finish delivery
uses stable call IDs and idempotent state transitions. A call with uncertain
termination remains unknown; this may represent real cost.

Worker attempts continue through existing `provider_calls`; avoid inserting
duplicate calls into the website ledger. Reports union normalized sources and
retain their provenance. Backfill existing LiteLLM cost values as SDK estimates,
not provider invoices. New OpenAI token estimates use a versioned rate snapshot
checked against official pricing at implementation time, including cache and
reasoning token semantics. Record `estimated`, `reported` or `unknown` cost basis
and currency. Never sum currencies without an explicit conversion source or
treat missing tokens/cost as zero. Display known spend, unpriced call count and
coverage together. Reconciliation to provider billing is future work.

## OpenAI migration and configuration

Use `OPEN_AI_KEY` and `OPEN_AI_MODEL=gpt-6-luna` for active website and worker
configuration. Python settings use explicit aliases for these names while
retaining the existing FITCHECK_* database, auth and worker settings. Provider
selection and execution registry must read the same resolved model configuration
in admission and worker execution. API does not need the provider key. Model
allowlisting begins with `gpt-6-luna`; unsupported values fail safely at startup
or admission, not after an arbitrary outbound destination has been selected.

Preserve existing public request/result contracts and grounding logic. Use
`https://api.openai.com/v1/chat/completions`, which the official model page lists
as supported. Keep the existing TypeScript OpenAI SDK and Python LiteLLM
completion boundary; select `openai/gpt-6-luna` in LiteLLM. Explicitly set
`reasoning_effort=none`, request JSON object output, use `max_completion_tokens`
for each operation's existing output cap and omit temperature. Remove DeepSeek's
`thinking` extension and base URL. No new tool calls or endpoint family are needed
for the existing prompted JSON schemas. Boundary tests must assert the actual
outbound body and reject silently dropped parameters. Preserve independent
transport/semantic attempt budgets, deadlines and disabled SDK automatic retries.

Python's provider-destination guard allows only HTTPS `api.openai.com` on port
443 with path `/v1/chat/completions` and no query or userinfo, rejects redirects
and unexpected outbound sends, and preserves cancellation
settlement, lease fencing and safe errors. New jobs freeze OpenAI model and a new
policy version. Existing DeepSeek envelopes and ledger rows are immutable.
Changing env values must not make an old queued job run on a different model.

Update `.env.example`, user-owned `.env.local`, `backend/.env.example`, worker
setup and deployment documentation. Preserve the user's supplied OpenAI key;
never echo it, write it into tracked files or display raw settings/errors.
Remove obsolete active DeepSeek variables only after OpenAI readiness is verified.
Historical DeepSeek ledger data and deployment records are preserved.

## Reporting and access

`python -m fitcheck_backend.metrics report` accepts explicit start/end, timezone,
environment and population, and outputs JSON or CSV to an operator-selected file.
CSV uses one row per metric/dimension/cohort with availability, value, numerator,
denominator, sample count, coverage and data start date; escape formula-leading
cells and emit no PII. Run with operator DB access; there is no publicly readable
cross-account report endpoint. A UI dashboard can later consume this contract.

Reports use a consistent DB snapshot, bounded date ranges (maximum 366 days),
parameterized SQL and short query timeouts. Raw event properties never become
arbitrary SQL dimensions. The cleanup/backfill commands are explicit, bounded and
idempotent; cleanup offers a dry run and touches only telemetry retention rows.

## Validation and rollout

Tests prove metric formulas on deterministic cohorts, incomplete-window exclusion,
UTC/DST boundaries, ordered funnels, duplicate/conflicting events, cookie reset,
separate identities/environments, unknown-cost coverage and multiple model calls.
HTTP tests cover forged sources/owners, invalid properties, missing bridge key,
cross-origin requests, body/rate limits and no secret/content logging. Website
tests cover events after committed UI actions, collector outages and bounded
queues. Provider SDK-boundary tests prove exact destinations/parameters, one send
per admission, 429/timeouts, cancellation and independent concurrent execution.

Run PostgreSQL integration and migration tests, contract drift checks, website
tests/typecheck/lint/build and both container builds. Verify that metrics queries
cannot multiply provider rows through joins or count audit calls as analyses.

Rollout applies additive migrations and deploys the collector with ingestion
disabled until bridge configuration is saved. Deploy website instrumentation,
enable collection, and verify a non-PII synthetic event plus operator report;
exclude and remove that synthetic test partition afterward. Ordinary local or
deployed telemetry verification makes no paid provider call.

Before provider migration, disable new backend admission, inspect all nonterminal
DeepSeek jobs and allow the current worker to drain them. Apply admission-off
using Reload on the existing API, retaining and verifying its pinned
pre-migration SHA/image rather than rebuilding the newly pushed branch. If any
jobs remain before 0007, abort and keep the old matching runtime/worker/key usable
against its unchanged schema; do not discard jobs or reinterpret their frozen envelopes.
Then deploy the OpenAI worker and admission registry consistently, verify schema,
startup/model configuration and health, and re-enable admission. Switch current
website routes and verify their configuration without printing keys. Configure
the same supplied key in the existing website and worker secret stores through
the supported mechanism. If Computer Use requires action-time confirmation for
new provider access, request it only when the concrete configuration is ready.

Paid live generation is not implicitly required. If a model compatibility canary
is necessary, request a concrete spend cap before performing it. Document whether
live generation was exercised and what offline verification cannot establish.
Record exact commits, CI, migrations, service health and collector/report checks.
Merge/push and deployment follow existing user authorization. Do not send messages
or Linear comments without a separate request.

Rollback disables ingestion/new admission, preserves stored telemetry and domain
data, and drains incompatible jobs with their matching worker/key. After 0007,
old exact-head-0006 backend images cannot be restored directly: API readiness and
worker startup schema gates reject that newer schema. Keep admission off and
retain or start the reviewed current 0007-compatible runtime, then repair forward.
A provider rollback requires a separately reviewed artifact supporting schema
0007 and the intended frozen provider registry/transport, validated against a
disposable 0007 DB and the intended jobs; none is prepared here. Recovery is less
immediate and job admission may remain unavailable during repair. Retain 0007,
all stored rows, envelopes and costs; never bypass schema gates, downgrade/reset
the database, delete jobs or rewrite frozen work. Return to the existing backlog only after this work's required checks
and deployment evidence are complete.

## Official model references

- Model identity and capabilities: https://developers.openai.com/api/docs/models/gpt-6-luna
- Current API model catalog: https://developers.openai.com/api/docs/models

These establish `gpt-6-luna`, not `gpt-6.1-luna`. Endpoint compatibility, pricing
and account access must be verified during implementation using official sources
and the installed SDK; model metadata alone does not prove access for this key.
