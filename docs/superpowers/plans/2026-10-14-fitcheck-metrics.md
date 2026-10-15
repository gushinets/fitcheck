# FitCheck Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect current website and backend usage and AI costs, and produce a provenance-aware JSON/CSV report without connecting the website's product flows to backend accounts.

**Architecture:** PostgreSQL stores typed events and a separate website provider-attempt ledger. A same-origin Next.js bridge validates browser observations and sends them to a credential-protected FastAPI collector; backend facts are transactional. An operator CLI calculates metrics from a consistent database snapshot.

**Tech Stack:** Existing Next.js/TypeScript/OpenAI SDK, FastAPI/Pydantic/SQLAlchemy/Alembic/PostgreSQL, Vitest and pytest; Node crypto for visitor signatures. No external analytics platform.

**Spec:** `docs/superpowers/specs/2026-10-14-fitcheck-metrics-openai-design.md`.

## Global Constraints

- This plan implements metrics first. Run `2026-10-14-fitcheck-openai-migration.md` afterward; it reuses the provider-attempt sink defined here.
- Keep visitors, local registrations, backend accounts, observation sources and deployment environments separate. No client-declared backend identity or success/cost facts.
- Events: 100-event memory queue, 20-event batches, 32 KiB, at most two retries, client clock tolerance five minutes; no disk event buffer.
- Sessions renew after 30 minutes inactivity; visible active pulses every 30 seconds count at most 30 seconds per pulse and stop after 30 seconds without activity.
- Raw retention 180 days; report maximum 366 days; default timezone Europe/Moscow; UTC storage and half-open ranges.
- Seven-day activation/onboarding/funnel/feedback windows exclude immature cohorts. D7/D30 retention uses day offsets [7,8) and [30,31) from first activation.
- Useful actions, event registry, formulas and unavailable metric reasons are defined in the spec. Empty ratios/percentiles are null; p50/p95 use nearest rank.
- Never store secrets, emails, IPs, raw URLs/query strings, prompts, profile/vacancy content, outputs or feedback notes. Known campaign codes only; unknown codes become `other`.
- Collector failure must not change current website product outcomes. Backend facts commit with their existing domain mutations. No paid live-model calls during verification.
- Preserve unrelated working-tree changes, especially user-owned `.env.local` and the existing `.env.example` change. Read installed Next.js guides before modifying its routes/cookies.

## Review Focus

1. Forged browser owner/source or cost cannot create a trusted account/provider fact (Tasks 1, 2, 3).
2. Collector outage during successful analysis does not fail the analysis or report fabricated complete cost coverage (Tasks 3, 5, 7).
3. Immature cohorts, DST changes and empty populations cannot inflate activation/retention or yield NaN (Task 7).
4. Replayed events, audit calls and retries must not count as new users or successful analyses (Tasks 1, 5, 7).
5. Account deletion and local cookie rotation must remove the right telemetry without touching another population (Tasks 4, 6, 7).

## File Structure

- `backend/src/fitcheck_backend/metrics/`: contracts/registry, collector, lifecycle events, backfill/cleanup, queries/calculations, report DTO/CSV/CLI.
- `backend/src/fitcheck_backend/storage/metrics.py` and additive `0004_metrics.py`: journal, website attempts and collection metadata; no schema reset.
- `backend/src/fitcheck_backend/api/metrics.py`: internal ingestion only, no cross-account public report.
- `lib/metrics/`: server cookie/bridge, browser queue, event types and provider-attempt delivery.
- `app/api/metrics/route.ts`: browser batch bridge and visitor deletion.
- Existing auth/profile/jobs/extraction and website UI/route files: call these small boundaries; keep domain behavior intact.

Backend test commands run in `backend/`. Integration commands require explicit
`FITCHECK_TEST_DATABASE_URL` pointing to the guarded disposable `_test` database;
reuse the existing test server on 55464 if occupied. Frontend commands run at root.

### Task 1: Typed event journal and website attempt storage

**Files:** Create `backend/src/fitcheck_backend/metrics/__init__.py`, `backend/src/fitcheck_backend/metrics/contracts.py`, `backend/src/fitcheck_backend/metrics/registry.py`, `backend/src/fitcheck_backend/storage/metrics.py`, `backend/src/fitcheck_backend/metrics/repository.py`, `backend/migrations/versions/0004_metrics.py`; modify `backend/src/fitcheck_backend/storage/models.py`, `backend/tests/integration/conftest.py`; create `backend/tests/metrics/test_contracts.py`, `backend/tests/integration/test_metrics_storage.py`; update migration-head fixtures/checks.

**Interfaces:** `MetricEvent` DTO with UUID `eventId`, registry `name`, integer `schemaVersion=1`, UTC `occurredAt`, `subjectId`, optional session/operation/domain key and registry-specific properties. Source/environment are trusted collector arguments. `WebsiteAttempt` DTO has unique call ID, parent operation ID, purpose, ordinal attempt, started/finished time, state, provider/model, versions and nullable usage/cost/basis. `MetricRepository(session).append(event, *, source, environment, received_at) -> bool` returns false for identical duplicates and rejects conflicts; `.settle_attempt(attempt, *, environment) -> bool` is idempotent and tolerates finish-before-start without downgrading terminal data. Error `MetricsError(code)` contains safe codes only.

- [ ] Write `test_registry_rejects_pii_unknown_names_and_forged_fact_properties`: a client event with ownerId or cost fails; score 0/100 passes, -1/101 fails; arbitrary UTM/notes fail. `test_event_duplicate_is_once_and_conflict_rejected` asserts one row for identical UUID retry, safe conflict for a changed payload. `test_attempt_finish_before_start_does_not_downgrade` asserts one terminal call and one cost. `test_migration_0003_to_0004_preserves_jobs_and_calls` proves additive upgrade and schema/package head consistency.
- [ ] Run `uv run --locked pytest tests/metrics/test_contracts.py -q`, observe missing DTO/registry failures; run new storage tests with `-m integration`, observe missing tables/repository.
- [ ] Implement the registry from the spec, strict bounded properties and rows with source/environment/time indexes, unique event/domain/call keys, nullable account association with explicit deletion semantics, and provider-state/currency constraints. Add collection-start metadata per source/environment so missing history is visible. Extend disposable fixture cleanup to truncate telemetry tables independently of owner cascades. Do not alter 0001–0003.
- [ ] Run `uv run --locked pytest -m 'integration or not integration' tests/metrics/test_contracts.py tests/integration/test_metrics_storage.py tests/integration/test_migrations.py tests/test_migration_package.py -q`; expect pass, preserved data and no metadata drift.
- [ ] Commit `feat: add versioned metrics journal and website attempt ledger`.

### Task 2: Authenticated bounded backend ingestion

**Files:** Create `backend/src/fitcheck_backend/metrics/collector.py`, `backend/src/fitcheck_backend/metrics/limits.py`, `backend/src/fitcheck_backend/api/metrics.py`; modify `backend/src/fitcheck_backend/config.py`, `backend/src/fitcheck_backend/api/app.py`, `backend/src/fitcheck_backend/api/runtime.py`, `backend/.env.example`; create `backend/tests/integration/test_metrics_http.py`, `backend/tests/metrics/test_limits.py`; export/update OpenAPI and generated TS schema.

**Interfaces:** `MetricsCollector(engine, settings, clock).ingest(batch: WebsiteBatch) -> IngestResult(accepted, duplicates)` and `.delete_visitor(visitor_id: UUID) -> int`. `WebsiteBatch` selects `website_client` or `website_server`, maximum 20 events/32 KiB; environment comes from credential scope/settings. POST `/internal/metrics/events`, POST `/internal/metrics/attempts`, DELETE `/internal/metrics/visitors/{visitorId}` require `X-FitCheck-Metrics-Key`. Settings: `metrics_enabled=False`, `metrics_environment` explicit development/production/test, `metrics_ingest_key: SecretStr | None`, known campaign code allowlist. Missing configuration leaves collector disabled. Website bridge key has no permission to create backend_server facts or read product records.

- [ ] Write `test_internal_ingest_rejects_missing_key_and_forged_backend_source`: unauthorized requests write nothing; valid bridge client observations cannot become backend events. `test_batch_21_and_32769_bytes_rejected`, `test_clock_outside_five_minutes_uses_received_time`, `test_conflicting_batch_rolls_back`, `test_visitor_delete_cannot_select_account_subject`, and rate-limit test asserting 60 requests/minute per configured bridge scope with a bounded persisted bucket (not user-controlled IDs).
- [ ] Run the new HTTP/limits tests and observe missing routes/collector failures.
- [ ] Implement constant-time credential comparison, no URL/query credentials, disabled routes returning safe service-unavailable, strict batch/source validation and atomic ingestion. The standalone collector owns an engine when auth runtime is disabled, otherwise shares its configured engine; close only owned resources. Reuse safe HTTP boundary errors/body limits and a distinct bridge limit namespace. Register internal operations in contract export without implying account auth or a public metrics read API.
- [ ] Run `uv run --locked pytest -m 'integration or not integration' tests/integration/test_metrics_http.py tests/metrics/test_limits.py tests/test_openapi.py tests/test_http_boundary.py -q`; export OpenAPI and run `pnpm backend:types`/`pnpm backend:types:check`; expect pass.
- [ ] Commit `feat: collect scoped website telemetry through an internal API`.

### Task 3: Website identity and nonblocking collection bridge

**Files:** Create `lib/metrics/types.ts`, `lib/metrics/cookie.ts`, `lib/metrics/bridge.ts`, `lib/metrics/client.ts`, `app/api/metrics/route.ts` and their `.test.ts` files; update root `.env.example` and deployment README as part of this deliverable.

**Interfaces:** `resolveVisitor(cookieValue, secret, now) -> {visitorId, cookieValue, isNew}` validates a domain-separated HMAC signature over UUID/version/issuance. `sendMetrics(batch, config, fetchImpl) -> Promise<boolean>` uses fixed `METRICS_BACKEND_URL`, server `METRICS_BRIDGE_KEY`, explicit `METRICS_ENVIRONMENT`, 1500 ms timeout, no redirects; returns false for delivery failure. Browser `createMetricsClient({send, now, eventId, timers}).track(name, properties, context?)`, `.flush()`, `.dispose()` own bounded queues, dedup retry IDs and session tracking. Browser POST `/api/metrics` accepts only client observations; DELETE deletes the cookie visitor, never a body-supplied identity. Production cookie HttpOnly, Secure, SameSite=Lax, path=/, expiry 180 days. Server signing key `METRICS_COOKIE_SECRET` never enters client bundle.

- [ ] Read installed Next route-handler, environment-variable and cookies guides. Write `test_cookie_tamper_rotates_without_trusting_claimed_visitor`, `test_cross_origin_and_server_fact_in_browser_batch_rejected`, `test_bridge_failure_returns_nonblocking_safe_result`, `test_queue_bound_100_batch_20_retry_2_same_event_ids`, `test_session_rotates_after_30_minutes`, `test_active_pulse_caps_30_seconds_and_stops_idle`, and `test_visitor_delete_uses_signed_cookie_only`.
- [ ] Run `pnpm exec vitest run lib/metrics app/api/metrics`; observe missing boundaries/functions.
- [ ] Implement registry parity using generated contract types plus runtime validation; accept exact same-origin browser requests, reject absent/foreign Origin on mutating browser routes. Use explicit local HTTP loopback exception only outside production. Rate-limit body acceptance before sending. Drop oldest unsent events at queue bound; expose only safe local delivery counters. Use received visitor identity from HttpOnly cookie and route-generated trusted context, never local account IDs. Cleanup timers/listeners on unmount; no page payload persistence.
- [ ] Run the new unit/route tests and `pnpm typecheck`; expect passing bounds, no credential in browser module exports and no change to existing API outcomes.
- [ ] Commit `feat: add safe website telemetry identity and batch delivery`.

### Task 4: Transactional backend lifecycle facts and retention tools

**Files:** Create `backend/src/fitcheck_backend/metrics/lifecycle.py`, `backend/src/fitcheck_backend/metrics/backfill.py`, `backend/src/fitcheck_backend/metrics/retention.py`; modify `backend/src/fitcheck_backend/auth/service.py`, `backend/src/fitcheck_backend/auth/email_service.py`, `backend/src/fitcheck_backend/auth/access.py`, `backend/src/fitcheck_backend/storage/profile_repository.py`, `backend/src/fitcheck_backend/jobs/admission.py`, `backend/src/fitcheck_backend/storage/job_queue.py`, `backend/src/fitcheck_backend/storage/job_publication.py`; create `backend/tests/integration/test_metrics_lifecycle.py`, `test_metrics_maintenance.py`.

**Interfaces:** `append_domain_event(session, *, name, owner_id, domain_key, occurred_at, properties, environment) -> None` uses Task 1 and existing transaction. `backfill_metrics(engine, *, environment, limit=1000) -> MaintenanceResult` processes bounded repeatable batches with deterministic domain keys. `cleanup_metrics(engine, *, now, dry_run=True, limit=1000) -> MaintenanceResult` selects only telemetry older than 180 days. `erase_account_metrics(session, owner_id) -> None` removes associated facts during account deletion; anonymous deletion aggregate does not retain deleted identity. Worker recovery event keyed by job ID + old execution token; heartbeat emits no activity.

- [ ] Write `test_registration_profile_and_job_facts_commit_or_rollback_with_domain`, `test_idempotent_admission_and_recovery_events_do_not_duplicate`, `test_publication_failure_never_records_success`, `test_account_delete_erases_only_own_metrics_preserves_provider_accounting`, `test_backfill_twice_is_idempotent_and_does_not_invent_views_or_claims`, `test_cleanup_180_days_dry_run_and_bounded_deletion`.
- [ ] Run new tests with `-m integration`; observe missing lifecycle/maintenance behavior.
- [ ] Instrument actual mutations inside their existing short transactions, keeping locked-row ordering and lease expiry checks intact. Domain keys for reconstructed facts match corresponding live facts. Reconstruct registrations, verification, revisions, job admission/terminal results only where exact timestamps exist; never infer execution claims from overwritten job started_at. Backfill records available range/source separately. Do not add planned ANY-650 routes. Make maintenance pagination stable and bounded.
- [ ] Run `uv run --locked pytest -m integration tests/integration/test_metrics_lifecycle.py tests/integration/test_metrics_maintenance.py tests/integration/test_auth_access.py tests/integration/test_job_admission.py tests/integration/test_job_publication.py tests/integration/test_job_queue.py -q`; expect pass without transaction/fencing regressions.
- [ ] Commit `feat: record authoritative lifecycle metrics and scoped retention`.

### Task 5: Current website operation and physical provider accounting

**Files:** Create `lib/metrics/provider.ts`, `lib/metrics/operations.ts`, associated tests; modify `app/api/analyze/route.ts`, `app/api/skill-suggestions/route.ts`, `app/api/extract/route.ts`, `lib/analysis/deepseek.ts`, `lib/skill-suggestions/deepseek.ts`; create `backend/tests/integration/test_website_attempts.py`.

**Interfaces:** `createWebsiteOperation({visitorId, environment, name, now}) -> OperationContext` creates server UUID. Export `ProviderAttemptSink` with `start(call): Promise<void>` and `finish(call): Promise<void>`, and `createProviderAttemptSink(context, bridge): ProviderAttemptSink`; methods are nonthrowing and use the same call ID. `recordProviderCall<T>({context, purpose, ordinal, send, summarize, sink}): Promise<T>` records exactly one SDK call, raw usage and safe failure; it must rethrow the original product error. `summarize` returns `ProviderUsage` only (tokens nullable, model, bounded safe state/latency, cost/basis nullable). Routes instantiate one operation context shared by generation/audit calls and emit validated terminal facts after existing service success.

- [ ] Write `test_analysis_audit_and_retry_are_three_calls_one_operation`, `test_collector_down_preserves_analysis_response_and_original_error`, `test_no_prompt_response_or_key_in_attempt_payload`, `test_missing_usage_is_unknown_not_zero`, `test_server_success_requires_grounding_validation`, `test_attempt_finish_replay_no_double_cost`. Existing DeepSeek mocks remain active for this plan; no live provider calls.
- [ ] Run `pnpm exec vitest run lib/metrics/provider.test.ts app/api/analyze app/api/skill-suggestions` and new PG attempt tests, observe missing sink/wrapper behavior.
- [ ] Instrument the actual SDK boundary, including grounding audits and existing semantic retries. Disable existing suggestion SDK hidden retries (`maxRetries:0`) so all physical calls are observable; pin this in an outbound-send test. Keep provider failures safe without raw exception messages. Metrics send timeout never consumes or extends the operation's product deadline. Record cached/uncached/reasoning token fields only if supplied. Website DeepSeek pricing remains unknown unless explicitly established; new OpenAI rate snapshot belongs to the next plan.
- [ ] Run all analysis/suggestions route, transport and service tests plus website attempt integration tests; expect output contracts unchanged and no double counting.
- [ ] Commit `feat: account for website operations and every provider attempt`.

### Task 6: Existing website product observations

**Files:** Modify `components/web/website-app.tsx`, `components/web/profile-editor.tsx`, `components/web/analysis-result.tsx`, `components/web/history-view.tsx`, `lib/web/repository.ts` only where event callbacks require it; create `components/web/website-metrics.test.tsx`; update relevant existing component tests.

**Interfaces:** Root `WebsiteApp` owns one Task 3 client; existing view/action callbacks emit typed events after successful mutations. Result context contains opaque result ID and score only; no profile/task text or notes. Telemetry callback is injected for tests and optional for components; root client is disposed on unmount. Local deletion calls the same-origin DELETE and rotates cookie even if deletion delivery fails, reporting safe observation-loss status.

- [ ] Write `test_ordered_local_registration_profile_analysis_view_events`, `test_failed_profile_save_does_not_emit_saved`, `test_result_first_view_not_recounted_by_rerender`, `test_skills_requested_accepted_and_history_adoption`, `test_feedback_emits_scores_without_note`, `test_local_delete_rotates_visitor_not_backend_identity`, `test_telemetry_failure_does_not_block_existing_flow`. Verify page-view capture excludes arbitrary route/query/UTM values.
- [ ] Run `pnpm exec vitest run components/web/website-metrics.test.tsx`; observe missing events.
- [ ] Emit the spec's available client events from actual successful flows. Do not treat local registration/login as backend auth, synthesize application outcomes or add new survey/status UI. Map first-touch campaign against configured known codes only. Activity pulses count observed foreground intervals; visibility/background transitions stop timers.
- [ ] Run `pnpm exec vitest run components/web lib/web lib/metrics` and `pnpm typecheck`; expect existing user flows and event assertions pass.
- [ ] Commit `feat: measure website onboarding and useful product actions`.

### Task 7: Metric calculations, consistent reports and CSV CLI

**Files:** Create `backend/src/fitcheck_backend/metrics/report_types.py`, `backend/src/fitcheck_backend/metrics/queries.py`, `backend/src/fitcheck_backend/metrics/calculations.py`, `backend/src/fitcheck_backend/metrics/report.py`, `backend/src/fitcheck_backend/metrics/csv_export.py`, `backend/src/fitcheck_backend/metrics/__main__.py`; create `backend/tests/metrics/test_calculations.py`, `test_csv.py`, `test_cli.py`, `backend/tests/integration/test_metrics_report.py`.

**Interfaces:** `ReportOptions(start: datetime, end: datetime, timezone: str='Europe/Moscow', environment: str, population: str)` validates range <=366 days. `MetricRow(metric, dimensions, value, numerator, denominator, sample_count, coverage, available, reason, data_start)` has no identities. `MetricReportService(engine).build(options) -> MetricReport` owns one repeatable-read, parameterized, timeout-bounded snapshot; `.to_json()` returns serializable report. `write_csv(report, stream) -> None` produces stable columns and protects spreadsheet formula-leading text. CLI `report --start --end --timezone --environment --population --format json|csv --output PATH`, `backfill` and `cleanup --dry-run` consume Tasks 4/7; cleanup requires explicit `--execute` to mutate.

- [ ] Write curated-cohort tests: `test_activation_2_of_4_is_50_percent_and_excludes_immature`, `test_funnel_requires_order_within_7_days`, `test_d7_d30_calendar_offsets_dst_and_complete_windows`, `test_empty_percentiles_and_ratios_are_null`, `test_useful_actions_exclude_page_view_login_retry`, `test_30_second_visible_pulses_bound_session_duration`, `test_deleted_and_rotated_subjects_not_linked`. Add `test_join_fanout_cannot_multiply_calls_or_feedback`, `test_audit_calls_not_analysis_count`, `test_unknown_cost_coverage_and_currencies_separate`, `test_reconstructed_history_cannot_produce_view_retention`, `test_unavailable_financial_survey_and_outcome_metrics_have_reasons`, `test_csv_formula_escaping_and_no_subject_ids`.
- [ ] Run the new calculation/CSV/CLI and report integration tests, observe missing report interfaces.
- [ ] Implement each spec formula, provenance/population dimensions and mature cohorts, using separate preaggregated event/operation/attempt queries before joining. Union website attempts with backend provider_calls without duplication; classify existing SDK costs as estimates. Show receipt/delivery uncertainty as an observation limitation, not a claimed percentage of all real activity. Export the same metric rows to JSON/CSV and include invalid options/date limits as safe CLI errors.
- [ ] Run `uv run --locked pytest -m 'integration or not integration' tests/metrics tests/integration/test_metrics_report.py -q`; invoke the CLI against disposable PG fixtures with explicit environment and timezone, assert deterministic report/CSV fields.
- [ ] Commit `feat: report product cohorts reliability and AI cost coverage`.

### Task 8: Whole-system verification and telemetry deployment

**Files:** Modify `backend/README.md`, root `README.md`, `.env.example`, `backend/.env.example`, CI if required; create `docs/deployments/2026-10-14-fitcheck-metrics.md`.

**Interfaces:** Existing Dokploy website/API/worker, CLI from Task 7; website env `METRICS_BACKEND_URL`, `METRICS_BRIDGE_KEY`, `METRICS_COOKIE_SECRET`, `METRICS_ENVIRONMENT=development`; backend metrics scope matches exactly. Root template documents server-only keys; no actual secrets in Git. No DeepSeek/OpenAI provider switch in this plan.

- [ ] Document configuration, formulas, collection limits, unavailable metrics, report/CSV commands, retention/deletion and current website/account identity limits. Document disabling collection rollback with preserved data.
- [ ] Run full backend PG suite, migration drift/package checks and OpenAPI export drift; run `pnpm backend:types:check`, `pnpm test`, `pnpm typecheck`, `pnpm lint`, `pnpm exec next build --webpack`, both backend Docker builds and `git diff --check`. Optional live tests remain skipped. Fix actual failures with regression evidence.
- [ ] Obtain a fresh whole-branch review using chosen execution skill, fix verified Important/Critical findings in one RED→GREEN pass, record exact checks and decisions.
- [ ] Commit, push dev and verify CI for exact runtime commit. Apply additive 0004_metrics, 0005_metrics_erasure and 0006_metrics_coverage through a verified migration runner (0001–0005 remain frozen); deploy collector with ingestion disabled, configure concrete bridge/cookie credentials using supported secret stores, then deploy website and enable ingestion. Observe Computer Use action-time approval if new access is granted; never output credentials or reuse OpenAI key as bridge key.
- [ ] Verify schema head and existing API/worker health. Submit a synthetic non-PII event in an explicitly excluded test scope through the real bridge, run report from operator container, assert received/deduplicated once and no public report access. Clean only the named synthetic scope; do not reset dev data. Verify one real non-paid website observation in development scope and its aggregate visibility. Record missing live-model coverage.
- [ ] Save exact deployment/CI/metric report evidence, mark this plan complete and commit/push clean documentation. Continue the OpenAI plan only after this verification; do not start unrelated backlog work yet.

## Plan self-review

Spec collection/identity/registry map to Tasks 1–3 and 6; backend facts, backfill,
retention and deletion to Task 4; current website/provider accounting to Task 5;
all formula/report/coverage requirements to Task 7; verification and deployment
to Task 8. OpenAI model/rate changes are exclusively in the companion plan.
Interfaces use the same MetricEvent, WebsiteAttempt, OperationContext,
ReportOptions and MetricRow names throughout. Each Review Focus case has a named
regression in its owning task. No billing/status/survey UI or ANY-653 integration
is introduced. Each runtime deliverable has its own failing/passing verification
and commit gate.

## Whole-branch coverage correction (2026-10-15)

Approved additive `0006_metrics_coverage` introduces nullable retention floor, fixed
backfill target and proven complete-through watermark. Reconstructed report periods
need completed coverage through their exclusive end; bounded partial batches cannot
turn missing outcomes into zero. Cleanup floors remain monotonic across late facts
and later drains. Maintenance is serialized before data locks; live owner-before-job
and owner-before-fact ordering remains intact. Registration-source backend cohorts
may consume exact same-account outcomes from both backend sources with explicit
coverage provenance. Reconstructed viewed retention remains unavailable.

Ordered authoritative job transitions establish historical pending state; recovery
queues the next execution and exhaustion requires its terminal fact. Mutable latest
domain claim timestamps cannot override the journal; unsupported legacy history is
unknown. Frozen migrations 0004/0005 are unchanged; OpenAI pricing uses next-free 0007.
