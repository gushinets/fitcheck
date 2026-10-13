# FitCheck Durable Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать durable account analysis/suggestion jobs, owner-scoped получение результата и отдельный worker с ограниченным recovery.

**Architecture:** API атомарно сохраняет frozen execution envelope в PostgreSQL. Worker захватывает jobs через SKIP LOCKED, поддерживает lease heartbeat и вызывает ANY-648 executor без удержания DB connection. Publication и terminal state коммитятся вместе после fencing; recovery допускает одно повторное исполнение.

**Tech Stack:** Python 3.12+, uv locked dependencies, FastAPI/Pydantic, SQLAlchemy/PostgreSQL 17, Alembic, asyncio, существующие PydanticAI/LiteLLM.

**Spec:** `docs/superpowers/specs/2026-10-13-fitcheck-durable-jobs-design.md`.

## Global Constraints

- Website only; guest admission ANY-651, history/feedback/reanalysis API ANY-650, import ANY-652, website UI integration ANY-653.
- No Redis/Celery, platform imports, provider calls in API or new product dependencies.
- Idempotency-Key 1..200; uniqueness owner/type/key; request hash excludes server snapshot/policy.
- At most two queued/running jobs per account across analysis/suggestions; duplicate uses no new slot.
- Poll 1 second; lease 150 seconds; heartbeat 20 seconds; executor analysis deadline 120 seconds; shutdown drain 130 seconds.
- Maximum two worker executions; ordinary final LLM failures are terminal, not automatic job retries.
- DB clock controls lease; fenced writes require owner/status/token/unexpired lease after lock acquisition.
- Unknown usage/cost remains null; no raw errors, secrets or provider content in logs/job.error.
- Admission defaults disabled; additive migration 0003, no database reset.
- Read relevant installed Next.js docs before writing code, including generated client contract changes.
- TDD for behavior: observed red then green; PostgreSQL barriers/events for races, no arbitrary sleeps.

## Review Focus

1. Duplicate admission after profile deletion/change, calibration update or deployment returns the original job (Task 2).
2. Heartbeat DB error or event-loop blocking during slow provider HTTP prevents stale publication (Tasks 3, 6).
3. Unsupported envelope/version or legacy bare-input job fails before spending provider money (Tasks 1, 4).
4. Late ledger completion after lease recovery never changes reconciled unknown back to succeeded (Tasks 1, 3).
5. Owner deletion and malformed job IDs cannot leak data or leave partial publication (Tasks 5, 7).

## File Map

- `jobs/types.py`, `jobs/envelope.py`, `jobs/errors.py`: internal immutable DTOs, version registry and safe domain failures.
- `jobs/admission.py`, `jobs/status.py`: account admission and owner-scoped reads.
- `storage/job_repository.py`: client request hash/legacy creation compatibility.
- `storage/job_queue.py`, `storage/job_publication.py`: claim/recovery/heartbeat and atomic fenced result persistence.
- `jobs/execution.py`: frozen-input adapter to existing analysis/suggestion executors.
- `worker/settings.py`, `worker/runner.py`, `worker/runtime.py`, `worker/health.py`, `worker/__main__.py`: process lifecycle and health.
- Existing provider ledger/types/gateway and migration 0003: execution token attribution and reconciliation.
- Existing API runtime/config/contracts plus `api/jobs.py`: routes, feature flag and admission limits.
- `backend/Dockerfile.worker`, `backend/compose.worker.yaml`, README/env/CI: deployable worker and reproducible verification.

All source paths above are relative to `backend/src/fitcheck_backend/` unless prefixed otherwise. New packages include `__init__.py`.

### Task 1: Frozen execution envelope and provider execution attribution

**Files:** Create `jobs/types.py`, `jobs/envelope.py`, `jobs/errors.py`, migration `backend/migrations/versions/0003_provider_execution_token.py`; modify `storage/accounting.py`, `storage/provider_repository.py`, `llm/types.py`, `llm/context.py`, `llm/gateway.py`; test `backend/tests/jobs/test_envelope.py`, `backend/tests/integration/test_provider_execution.py`, existing migration/ledger tests.

**Interfaces:**
- `ExecutionVersions`: provider, model, generation/audit prompt/schema and policy version strings; worker checks supported combinations.
- `AnalysisEnvelope`: envelope_version literal 1, request AccountAnalysisStart, profile FreelancerProfile, memory CalibrationEntry DTO list, versions ExecutionVersions.
- `SuggestionsEnvelope`: envelope_version 1, request SkillSuggestionStart, versions ExecutionVersions.
- `decode_envelope(job_type: str, payload: dict) -> AnalysisEnvelope | SuggestionsEnvelope`; `validate_supported_versions(envelope) -> None` raises JobError before HTTP.
- `JobError(code: str)` maps to existing safe ErrorBody; no new raw detail contract.
- Add optional `execution_token: UUID | None = None` to OperationContext and ProviderAttempt. ProviderCall nullable UUID execution_token plus `(job_id, execution_token, state)` reconciliation index.
- `ProviderLedger.start(attempt)` with execution_token checks current running/unexpired job token under row lock before inserting the call; tokenless internal legacy callers retain their ownership checks. `ProviderLedger.finish(...)` locks the row and preserves a reconciled unknown/process_lost state. Existing succeeded→failed domain-rejection behavior remains supported.

- [ ] Write tests `test_envelope_rejects_unknown_version`, `test_envelope_copies_inputs`, `test_legacy_payload_fails_before_http`: assert unsupported/extra server fields fail validation, copy unchanged after caller mutation, no fake HTTP calls. Add PG `test_late_finish_preserves_process_lost` asserting state unknown and original nullable usage after late finish; `test_execution_token_is_nullable_for_old_calls`.
- [ ] Run `cd backend && uv run --locked pytest tests/jobs/test_envelope.py -q` and PG integration file with test DSN; observe missing implementation failures.
- [ ] Implement the DTOs/version registry and token propagation, then additive migration 0003. Keep 0001/0002 unchanged; preserve legacy ledger and SDK retry tests.
- [ ] Run new tests plus `tests/llm`, `tests/integration/test_provider_execution.py`, `tests/integration/test_migrations.py` with explicit integration marker/DSN; assert pass and upgrade 0002→0003 retains rows.
- [ ] Commit `feat: freeze job inputs and attribute provider calls to executions`.

### Task 2: Atomic idempotent account admission

**Files:** Create `jobs/admission.py`; modify `storage/job_repository.py`, `auth/rate_limit.py`; test `backend/tests/integration/test_job_admission.py`, existing storage job tests.

**Interfaces:**
- `AdmissionResult(job_id: UUID, type: str, status: str)` immutable value.
- `JobAdmission(engine, limiter, policies).start_analysis(*, owner_id: UUID, request: AccountAnalysisStart, idempotency_key: str, client_ip: str) -> AdmissionResult`.
- Same `.start_suggestions(..., request: SkillSuggestionStart, ...) -> AdmissionResult`.
- Internal `request_digest(job_type: str, request_payload: dict) -> str`; existing `get_or_create_job(...)` callers for import remain valid.

- [ ] Write PG tests `test_same_key_concurrent_admission_creates_one_job` (barrier, same IDs, one envelope), `test_changed_input_same_key_conflicts`, `test_new_key_creates_new_job`, `test_duplicate_ignores_changed_profile_memory_policy` (unchanged envelope, no extra quota/rate charge), `test_two_active_jobs_cap_is_atomic` (parallel third request rejected), `test_foreign_revision_rejected`, `test_admission_rollback_has_no_job`.
- [ ] Run `uv run --locked pytest -m integration tests/integration/test_job_admission.py -q`; observe red.
- [ ] Implement owner FOR UPDATE transaction; find/hash-check duplicate first; enforce supported account identity, limit and existing user/IP rate limiter for new requests. Add `jobs` rate policy: user 10 per 60 seconds, IP 60 per 900 seconds. Read requested revision and calibration in same transaction; freeze policies and insert job. Make limiter transaction boundary explicit: rate consumption may precede a failed create, but cannot create job on rollback; duplicates bypass new-request consumption.
- [ ] Run admission tests and existing job/ownership/profile integration tests; assert repeated request hash depends on client DTO only and active cap sums both types.
- [ ] Commit `feat: admit immutable account jobs with idempotency and limits`.

### Task 3: Queue claim, heartbeat and bounded recovery

**Files:** Create `storage/job_queue.py`; test `backend/tests/integration/test_job_queue.py`.

**Interfaces:**
- `JobLease(job_id: UUID, owner_id: UUID, type: str, execution_token: UUID, attempts: int, input: dict)` immutable value in `jobs/types.py`.
- `JobQueue(engine, *, lease_seconds: float = 150, max_attempts: int = 2)`.
- `.claim() -> JobLease | None`: short transaction, supported jobs only, DB clock, SKIP LOCKED, at most one execution returned.
- `.heartbeat(lease: JobLease) -> bool`: only matching unexpired lease may extend.
- `.recover_expired(*, limit: int = 100) -> int`: bounded locked sweep, mark old started ledger rows unknown/process_lost; requeue if attempts < 2, otherwise terminal fail. Called every polling cycle, not just idle.

- [ ] Write `test_two_workers_claim_one_execution`, `test_locked_candidate_is_skipped`, `test_heartbeat_cannot_resurrect_expired_lease`, `test_stale_token_cannot_heartbeat`, `test_recovery_requeues_once_then_fails`, `test_recovery_preserves_succeeded_provider_usage`, `test_recovery_scopes_started_calls_to_old_token`, `test_import_jobs_are_not_claimed`. Assert attempts 1 then 2; recovery after second loss has no third execution; compare DB time rather than Python clock.
- [ ] Run `uv run --locked pytest -m integration tests/integration/test_job_queue.py -q`; observe red.
- [ ] Implement claims/recovery with statement_timeout=5000ms and lock_timeout=3000ms per transaction; configure connection/pool timeout 5 seconds for job storage adapters. Recovery and claim may be separate short transactions; each independently protects row state. Enforce deterministic ordering and no starvation of expired jobs while queued work remains.
- [ ] Run queue tests with two real PG connections and barriers. Verify only one job token wins, expired heartbeat returns false, unknown ledger is durable and late finish from Task 1 cannot reverse it.
- [ ] Commit `feat: lease PostgreSQL jobs and recover expired executions`.

### Task 4: Execute frozen jobs through the existing LLM runtime

**Files:** Create `jobs/execution.py`; modify `analysis/service.py`, `skill_suggestions/service.py`, `llm/context.py` as needed; test `backend/tests/jobs/test_execution.py`, `backend/tests/integration/test_job_execution.py`.

**Interfaces:**
- `FrozenJobExecutor(runtime).execute(lease: JobLease) -> AnalysisResult | list[str]` async; uses decode/validate envelope and a new operation UUID with lease.execution_token.
- `AnalysisService.analyze_prepared(*, context: OperationContext, value: AnalysisInput, snapshot: AnalysisSnapshot) -> AnalysisResult` async; no profile/calibration reread.
- Existing `.analyze(...)` assembles prepared inputs and delegates, preserving current callers/tests.

- [ ] Write `test_execution_uses_admitted_memory_profile_and_versions`, `test_unsupported_version_spends_zero_calls`, `test_legacy_bare_job_input_spends_zero_calls`, `test_execution_deadline_is_shared_by_generation_and_audit`, `test_suggestions_use_frozen_request`; PG test asserts connection pool checked-out count zero during paused provider HTTP. Two recovery executions use distinct operation UUIDs but same frozen profile/memory.
- [ ] Run the execution files, observe red.
- [ ] Implement adapter around cached existing executors. Resolve stored versions against server registry; unsupported combinations fail safely. Start shared budget before context preparation; never refresh memory/profile at runtime. Preserve gateway physical/semantic retry limits.
- [ ] Run execution, analysis and suggestions suites; assert unchanged direct-service results and no direct SDK imports outside approved boundaries.
- [ ] Commit `feat: execute frozen job snapshots through the LLM gateway`.

### Task 5: Fenced atomic publication and consistent result reads

**Files:** Create `storage/job_publication.py`, `jobs/status.py`; modify `contracts/jobs.py`; test `backend/tests/integration/test_job_publication.py`, `backend/tests/jobs/test_status_contracts.py`.

**Interfaces:**
- `JobPublication(engine).succeed_analysis(lease: JobLease, result: AnalysisResult) -> UUID | None` (analysis ID or fence lost).
- `.succeed_suggestions(lease: JobLease, skills: list[str]) -> bool`; `.fail(lease: JobLease, error: ErrorBody) -> bool`.
- `JobStatusReader(engine).get(*, owner_id: UUID, job_id: UUID) -> JobState`; absent/foreign/unsupported type raises safe not_found JobError.
- AnalysisSucceeded adds required `result: AnalysisResource`; new `JobAdmissionResource` has job_id, supported type and four-state status.

- [ ] Write PG `test_analysis_and_terminal_state_commit_atomically`, `test_publication_rollback_leaves_no_vacancy_or_analysis`, `test_stale_success_and_failure_cannot_publish`, `test_lease_expiring_while_waiting_for_lock_cannot_publish`, `test_two_publishers_create_one_analysis`, `test_owner_deleted_during_execution_has_no_partial_result`, `test_read_success_has_matching_snapshot`, `test_foreign_owner_get_is_not_found`. Contract tests assert success embeds result and failed excludes snapshot/input.
- [ ] Run new tests, observe red.
- [ ] Implement row lock then fresh DB-time fence; insert same-owner immutable vacancy/analysis plus terminal update in one transaction; suggestions output follows existing CHECK. Reader joins owner-scoped result/annotation under one consistent statement/read snapshot. Keep analysis output null and clear leases on all terminal paths.
- [ ] Run publication/status and existing constraints/ownership tests; assert no succeeded analysis job without stored result and no payload mutation on retry.
- [ ] Commit `feat: publish job results atomically with lease fencing`.

### Task 6: Separate worker lifecycle, async heartbeat and health

**Files:** Create `worker/settings.py`, `worker/runner.py`, `worker/runtime.py`, `worker/health.py`, `worker/__main__.py`, `backend/Dockerfile.worker`, `backend/compose.worker.yaml`; modify `backend/.env.example`; test `backend/tests/worker/test_runner.py`, `test_settings.py`, `test_health.py`, `backend/tests/integration/test_worker_recovery.py`.

**Interfaces:**
- `WorkerSettings`: poll_interval=1, lease_seconds=150, heartbeat_seconds=20, drain_seconds=130; finite positive validation, heartbeat < lease, lease >= analysis deadline + 30.
- `WorkerRunner(queue, executor, publication, settings, health).run_forever()` async; `.request_shutdown() -> None`.
- `.process(lease: JobLease) -> None` async owns heartbeat and execution tasks; synchronous DB calls use bounded thread adapter, no shared Session between threads.
- `WorkerRuntime(settings)` owns engine/LlmRuntime, validates schema/key at startup, closes resources on exit.
- `python -m fitcheck_backend.worker` entrypoint; `python -m fitcheck_backend.worker.health` returns exit 0 only for fresh healthy local marker. Marker contains no secrets, has atomic writes and per-process boot identity.

- [ ] Write runner tests using events: `test_heartbeat_runs_during_slow_provider`, `test_blocked_db_call_does_not_block_heartbeat_event_loop`, `test_failed_heartbeat_cancels_execution_and_never_publishes`, `test_shutdown_stops_claim_and_drains_current_job`, `test_drain_timeout_leaves_recoverable_job`, `test_recovery_runs_under_continuous_backlog`. Assert defaults exactly 1/150/20/130 and reject NaN/inf/invalid relationships. Health tests cover stale marker, process restart and failed startup.
- [ ] Run `uv run --locked pytest tests/worker -q`, observe red.
- [ ] Implement sequential jobs with concurrent heartbeat; safe error mapping, no raw payload logs. On fence/heartbeat loss cancel HTTP best effort and refuse publication; DB transaction timeouts bound adapter work even after asyncio cancellation. SIGTERM drains within 130 seconds; compose stop_grace_period=140s. Worker health updates during busy work; startup requires provider key and schema head. Worker image shares lockfile/package build, runs nonroot and health command rather than API HTTP check.
- [ ] Add PG crash tests after claim, after fake provider success and before publication. Restart yields one recovery, separate operation IDs, preserved first cost plus second cost, one published analysis; second crash yields failed with no third HTTP execution.
- [ ] Run worker and crash suites, build worker image and check missing-key startup fails safely; health command gives correct status without network provider calls.
- [ ] Commit `feat: run durable jobs in a separate healthy worker process`.

### Task 7: Account job routes and contract export

**Files:** Create `api/jobs.py`; modify `api/app.py`, `api/runtime.py`, `config.py`, `contracts/operations.py`, `backend/.env.example`, `contracts/fitcheck.openapi.json`, `lib/backend/generated/schema.ts`; test `backend/tests/integration/test_jobs_http.py`, `backend/tests/test_openapi.py`, existing HTTP boundary tests.

**Interfaces:** AuthRuntime exposes `.jobs` JobAdmission and `.job_status` JobStatusReader; Settings.jobs_enabled=False. Routers implement the three spec endpoints using existing verified_principal/CSRF dependencies and safe errors. API never constructs LlmRuntime to admit/read jobs.

- [ ] Read installed Next.js route-handler/type guidance and existing profile/extraction router patterns before code changes.
- [ ] Write HTTP tests `test_admission_returns_202_reference_and_status`, `test_duplicate_returns_terminal_status`, `test_invalid_or_duplicate_idempotency_headers_rejected`, `test_guest_and_unverified_account_rejected`, `test_csrf_required`, `test_foreign_and_malformed_job_ids_do_not_leak`, `test_disabled_admission_preserves_existing_get`, `test_api_jobs_work_without_provider_key`, `test_job_get_contains_committed_result`. Assert no provider HTTP in POST or GET.
- [ ] Run HTTP tests, observe red.
- [ ] Wire verified-account endpoints and feature flag; duplicate header checks use getlist, not collapsed values. Implement malformed IDs as safe validation failures and foreign IDs as 404. Return stored current status on duplicate. Update operation implementations and admission/result DTO references while leaving history/import/guest routes planned.
- [ ] Export `cd backend && uv run --locked python scripts/export_openapi.py`; run root `pnpm backend:types`, then both drift checks. Run HTTP/openapi suites, frontend typecheck and contract tests.
- [ ] Commit `feat: expose account job admission and owner-scoped results`.

### Task 8: Whole-system verification, review and dev rollout

**Files:** Modify `backend/README.md`, `.github/workflows/ci.yml` as needed; create `docs/deployments/2026-10-13-any-649-durable-jobs.md`.

**Interfaces:** Follow prior ANY-648 deployment record for dev URLs/app locations; separate worker deployment targets dev branch and worker Dockerfile. Migration runner remains the existing standalone command, not worker startup migration.

- [ ] Document local worker setup, limits, failure/repeated-cost semantics, unsupported legacy envelope handling, admission flag and health/shutdown. Document rollback: disable new admission, preserve GET and DB data, drain worker; do not downgrade 0003 with populated rows.
- [ ] Run `docker compose -p fitcheck-any649 -f backend/compose.test.yaml up -d --wait`. With explicit disposable FITCHECK_TEST_DATABASE_URL run `cd backend && uv run --locked pytest -m 'integration or not integration' -q`; paid canary remains skipped. Run migration check against that DB, wheel packaging and OpenAPI drift.
- [ ] Run root `pnpm backend:types:check`, `pnpm test`, `pnpm typecheck`, `pnpm lint`, `pnpm exec next build --webpack`; assert pass. Run `git diff --check`; record exact results and skipped optional checks.
- [ ] Request fresh whole-branch code review under chosen execution skill; fix verified findings with regression red/green and affected checks. Do not claim completion before final evidence.
- [ ] Commit verified changes, merge to dev if execution used isolated branch, push and verify CI for exact runtime commit. Existing user authorization covers dev merge/deploy; no renewed approval for ordinary rollout.
- [ ] Apply additive 0003 to dev using approved migration runner, deploy API and new worker with existing DB configuration. Configure provider credential only in worker using supported secret mechanism without exposing it. If tool approval rejects credential transfer or deployment, report the exact blocker instead of bypassing it. Confirm schema head, API health, worker startup/health, and anon job access rejection.
- [ ] Enable admission only after worker checks pass; verify durable account POST/GET with fake-provider isolated integration evidence. Live paid canary is not required or implicitly authorized by rollout. Record whether a real dev job/provider call was exercised; leave no claim of live paid execution when omitted.
- [ ] Save deployment evidence with commit, CI URL, migration revision, worker service and health, limitations; update ANY-649 status to Done only when acceptance criteria and required rollout are complete. Do not send Linear comments/messages without separate authorization.
- [ ] Commit evidence, push and ensure working tree clean; report outcome, verification and material limitations in Russian.

## Plan self-review

Spec sections map to Tasks 1–8: versioned snapshots/ledger (1), idempotency and
atomic admission (2), queue/fencing/recovery (3), frozen LLM execution (4),
atomic result/status (5), worker lifecycle/health (6), access/contracts (7),
verification and rollout (8). All five Review Focus cases have named tests.
Recovery uses explicit sweep then claim, retaining the spec's bounded two
executions; stale tokens cannot publish or revive reconciled ledger outcomes.
