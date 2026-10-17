# ANY-652 Local Account Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export only the selected local user's data and durably import it into a verified server account without overwrites or duplicates.

**Architecture:** Add a bounded versioned export/import contract and explicit legacy snapshots. Extend the existing queue with an import executor whose per-item transactions fence the lease and atomically persist records, receipts and outcomes. Existing server profile/preferences win conflicts; local data is never deleted.

**Tech Stack:** TypeScript, IndexedDB/fake-indexeddb, Vitest, FastAPI/Pydantic, SQLAlchemy, PostgreSQL17, Alembic, pytest; existing dependencies only.

**Spec:** `docs/superpowers/specs/2026-10-17-any-652-local-account-import-design.md`

## Global Constraints

- Require an active verified server account, allowed Origin, account CSRF proof and Idempotency-Key for admission.
- Maximum1000 rows and at most the configured HTTP body limit, with a hard import ceiling of5MiB. The effective limit is the smaller limit.
- An existing server profile wins; differences are reported rather than overwritten.
- No password digest, salt, email, authentication/session object or provider operation credential is included.
- Local data is never deleted automatically, including after successful completion.
- Missing historical profile stays null; never fill it from today's selected profile.
- No LLM repair is attempted for old data.
- Keep native/guest job envelopes unchanged; no provider call or analysis credit is consumed by imports.
- Preserve user edits and `.env` files; isolate implementation from dev before executing this plan.
- Read relevant installed Next.js guides before any Next.js code change, per AGENTS.md.

## Review Focus

- Selection changes during export must never send the newly selected user's data under the old identity (Task2).
- The same external row ID from two different local users must remain separate, while retries within one source deduplicate (Task3).
- Lease expiration during a blocked transaction must prevent the stale worker from publishing after the lock becomes available (Task5).
- History erased during an import must serialize against publication; erasing an account must stop further writes (Task5).
- Legacy evidence and missing snapshot fields must remain explicitly unverified/unknown in history and recalculation (Task1/6).

## File ownership

- `contracts/imports.py`: request, row validation and progress/report DTOs; no persistence.
- `contracts/resources.py`, `storage/payloads.py`: legacy snapshot variants and codecs.
- `lib/web/local-export.ts`: allowlisted mapping, validation, byte limits and batching.
- `lib/web/repository.ts`: readonly IndexedDB export transaction; no network operation.
- `storage/imports.py`, `storage/import_repository.py`: progress models and atomic fenced item writes.
- `imports/admission.py`, `imports/status.py`: authenticated idempotent admission and owner-scoped polling.
- `imports/execution.py`: orchestrate resumable items, no provider dependency.
- `api/imports.py`, worker/runtime integration: adapt existing API/worker boundaries.
- Migration0009: additive schema changes supporting these boundaries.

## Execution setup

- [ ] Read the spec and plan; use `using-git-worktrees` to create `feat/any-652-local-import` from the current dev commit, including the committed spec and plan.
- [ ] Run a clean baseline using task-owned PostgreSQL project `fitcheck-any652`; port55464 is available after ANY-651 cleanup, but verify before starting it. Never reset a shared DB.
- [ ] Reuse the locked root backend virtualenv if available, explicitly setting worktree source/PYTHONPATH and disabling dotenv/provider credentials in test subprocesses. Create a test wrapper specific to ANY-652 rather than editing the prior task's wrapper.

### Task 1: Versioned import and truthful legacy history contracts

**Files:** Create `backend/src/fitcheck_backend/contracts/imports.py`, `backend/tests/imports/test_contracts.py`; modify `contracts/resources.py`, `contracts/jobs.py`, `storage/payloads.py`, `storage/history_repository.py`, `history/service.py`; test `backend/tests/test_openapi.py`, `backend/tests/integration/test_history_http.py`.

**Interfaces:** Export `LocalImportRequest`, `ImportRow`, `ImportReport`, `ImportItemOutcome`, `LegacyAnalysisSnapshot`. `parse_import_row(raw: dict) -> ImportRow` validates allowlisted row data; invalid rows are converted to typed outcomes by the executor. `decode_snapshot(value: dict)` returns a native or legacy snapshot. `ImportState` gains progress/report without changing native job states.

- [ ] Write failing tests: version1 source `website_indexeddb_v1`, sourceUserId, optional profile/locale, maximum1000 rows; unsupported versions, duplicate IDs, credentials/unknown fields rejected. A malformed individual row remains addressable by a bounded external ID for a later invalid outcome; missing/unusable IDs use stable row-index report identity and cannot produce receipts.
- [ ] Write failing tests: native snapshot roundtrip unchanged; imported snapshot has explicit legacy discriminator/schema, null server revision/prompt/policy, nullable historical profile/locale and retained unverified evidence. `profileChanged` is null for legacy records; recalculation selects a real current profile.
- [ ] Run `python -m pytest -o addopts= backend/tests/imports/test_contracts.py backend/tests/test_openapi.py -q` under the isolated test environment; verify failures identify missing contracts rather than fixture errors.
- [ ] Implement DTOs, normalized canonical row representation and codec/history changes. Keep result validation strict and evidence provenance explicit. Profile legacy normalization uses existing defaults; exclude deprecated monthly income.
- [ ] Run contract/history tests and commit `feat: define local import and legacy snapshot contracts`.

### Task 2: Complete selected-user export from IndexedDB

**Files:** Create `lib/web/local-export.ts`, `lib/web/local-export.test.ts`; modify `lib/web/repository.ts`, `lib/web/memory-repository.ts`, `lib/web/types.ts`; extend `lib/web/repository.test.ts`.

**Interfaces:** Add `WebsiteRepository.exportLocalData(selectedUserId: string): Promise<LocalImportRequest>` and pure `batchLocalExport(value: LocalImportRequest, maxBytes: number): LocalImportRequest[]`. Client DTO names and aliases match Task1's generated wire format. Export does no fetch and no mutation.

- [ ] Write failing fake-indexeddb tests creating two local users, each with overlapping history IDs in separate test source databases; only selected owner data is exported. Cover switched/stale selection, no session, >50 rows, old schemas, missing URL and malformed stored row.
- [ ] Assert serialized export contains neither password/hash/salt/email/session nor providerOperationId. Assert exporting does not alter local data. Test byte measurement in UTF-8 using non-ASCII text, exactly1000 and1001 rows, one oversized record and deterministic batches under the effective byte limit.
- [ ] Run `pnpm exec vitest run lib/web/local-export.test.ts lib/web/repository.test.ts`; confirm RED for missing operation.
- [ ] Implement one readonly transaction over active session, user/profile/preferences/history; read all owner-index rows without HISTORY_LIMIT. Build fields with allowlists and preserve per-row validation failures for the server report. Batched export repeats optional profile/preferences and source identity; refuses an indivisible oversized row without truncation.
- [ ] Run client repository/export tests and `pnpm typecheck`; commit `feat: export selected local account data safely`.

### Task 3: Durable import receipts and atomic publication

**Files:** Create `backend/src/fitcheck_backend/storage/imports.py`, `storage/import_repository.py`, `backend/migrations/versions/0009_local_account_import.py`, `backend/tests/integration/test_import_repository.py`; modify `storage/work.py`, `storage/models.py`, migration tests.

**Interfaces:** `ImportRepository(session)` provides `apply_profile(lease, request) -> outcome`, `apply_preferences(lease, request) -> outcome`, `apply_row(lease, index, row) -> ImportItemOutcome`, `record_invalid(lease, index, reason) -> ImportItemOutcome`, and `report(job_id, owner_id) -> ImportReport`. Callers wrap each operation in `job_transaction`; operations require `fenced_job` before writes.

- [ ] Write failing PostgreSQL tests for migration0008→0009 preserving existing records, empty DB→head and no schema drift. Extend receipt uniqueness with sourceUserId and retain old receipts using an explicit reserved legacy-source sentinel; existing rows are not deleted.
- [ ] Write tests: first row inserts analysis/vacancy/feedback/receipt/outcome together; crash before commit inserts none. Same source+hash skips, changed hash conflicts, distinct sourceUserId imports separately; replay preserves later annotations/status edits.
- [ ] Write profile/preference tests: absent creates, equal skips, different conflicts; recorded profile outcome survives retry. Historical profile is independent of current imported profile. Timestamps roundtrip UTC, feedback creation retained, missing URL valid.
- [ ] Run `python -m pytest -o addopts= backend/tests/integration/test_import_repository.py backend/tests/integration/test_migrations.py -q`; confirm RED.
- [ ] Implement additive migration, owner-scoped progress/item models and receipt changes. Unique item index `(job_id, item_index)` makes outcomes replayable. Owner/job foreign keys cascade on erasure. Counters derive from durable outcomes to prevent double counting. ImportEntry deletion follows history deletion.
- [ ] Run repository/migration/schema checks; commit `feat: persist resumable local import outcomes`.

### Task 4: Verified account admission and import status API

**Files:** Create `backend/src/fitcheck_backend/imports/__init__.py`, `imports/admission.py`, `imports/status.py`, `api/imports.py`, `backend/tests/integration/test_import_http.py`; modify `api/app.py`, `api/runtime.py`, `api/middleware.py`, `contracts/operations.py`.

**Interfaces:** `ImportAdmission.start(principal, request: LocalImportRequest, key: str) -> ImportReference`; `ImportStatusReader.get(principal, import_id) -> ImportState`. AuthRuntime exposes `imports` and `import_status`. Existing `/v1/import-jobs` routes become implemented.

- [ ] Write HTTP tests: verified account admission202; unverified403, missing session401, guest denied, missing/bad Origin/CSRF403; jobs disabled503. Foreign/expired session polling denied, foreign ID404. Test effective5MiB/request ceiling and requestId error envelope without echoing uploaded values.
- [ ] Test same key/hash returns original ID, changed body409, concurrent admissions create one job; active account ceiling2 includes imports and rejects a third active job. Assert no product reservation/provider call is created.
- [ ] Run `python -m pytest -o addopts= backend/tests/integration/test_import_http.py -q`; confirm RED.
- [ ] Implement owner→user→job lock order and existing active-session validation. Hash canonical bounded input including source identity. Use sync routes/dependencies for database I/O; fail closed on storage errors. Status includes typed item outcomes/counters and separate profile/preferences results, scoped to owner.
- [ ] Run HTTP and existing auth/job tests; commit `feat: admit and report authenticated import jobs`.

### Task 5: Worker execution, recovery and lease fencing

**Files:** Create `backend/src/fitcheck_backend/imports/execution.py`, `backend/tests/integration/test_import_execution.py`; modify `worker/runtime.py`, `worker/runner.py`, `storage/job_queue.py`, `storage/job_publication.py`; extend `backend/tests/worker/test_runner.py`, `backend/tests/integration/test_worker_recovery.py`.

**Interfaces:** `ImportExecutor(engine).execute(lease: JobLease) -> ImportReport` is async and sends database transactions to threads. Worker routes import leases to this executor; `JobPublication.succeed_import(lease, report)` terminally publishes only under the live fence. Queue claim/recovery includes import alongside existing supported types.

- [ ] Write failing tests for zero-provider import completion, per-item invalid/conflict outcomes with successful siblings, partial commit then process loss/recovery, two attempts exhausted then resubmission under new key, and unchanged global receipts across jobs.
- [ ] Test lease expiration while blocked on owner lock: time must be rechecked after lock acquisition, with no stale row/progress writes. Test heartbeat loss/drain cancellation, concurrent workers, account erase and history clear during import. Report counts sum to history length on completion and never count profile/preferences as rows.
- [ ] Run worker and import execution tests; verify RED before wiring imports into queue/publication.
- [ ] Implement per-item fenced transactions, durable metadata outcomes and bounded report construction. Reuse queue max_attempts2 and heartbeat/recovery; do not route import failures through LLM logic. Stop promptly after lease loss; cancellation may leave an in-flight transaction only if it still owns a valid fence.
- [ ] Run worker/recovery/quota tests with imports and native/guest jobs together; commit `feat: execute and recover local imports without duplication`.

### Task 6: Contracts, integration proof and operational handoff

**Files:** Modify `contracts/fitcheck.openapi.json`, `lib/backend/generated/schema.ts`, `backend/tests/test_openapi.py`, integration history/recalculation tests, `README.md`; create `docs/deployments/2026-10-17-any-652-local-import.md`.

**Interfaces:** Existing `pnpm backend:types` and backend OpenAPI export remain authoritative. ANY-653 receives export/batching APIs, authenticated endpoints, progress/error codes and explicit legacy snapshot rendering requirements.

- [ ] Add integrated test exporting a real local fixture then importing into a verified account through HTTP/worker: skills/levels/currencies/locale, snapshots, evidence, dates, feedback and source URLs survive; second run skips; conflicting server profile survives; source local database remains untouched.
- [ ] Cover legacy rows with missing profile/locale/URL in history, filtering and recalculation; verify normal guest/native snapshots and v1/v2 job execution regressions remain passing. Legacy evidence must be identifiable as unverified by consumers.
- [ ] Regenerate contracts and run `pnpm backend:types:check`, `pnpm test`, `pnpm typecheck`, `pnpm lint`, `pnpm exec next build --webpack`; all must exit0. Run isolated full backend suite including PostgreSQL; only paid provider canary may remain intentionally skipped.
- [ ] Build API and worker images; migrate disposable PostgreSQL to0009, check schema drift/health and run an actual zero-provider import smoke, then remove only task-owned disposable containers/volumes.
- [ ] Document request/report examples, limits, resubmission behavior, legacy snapshot handling and deletion semantics. Record actual test counts and failures resolved, not anticipated results. Commit `docs: verify and document local account import`.
- [ ] Obtain whole-branch review and resolve findings under the chosen execution workflow. Integrate/push dev only after checks; coordinated migration/deploy uses paused admission and matching API/worker, followed by live health and nonpaid import smoke. Record evidence, restore temporarily changed settings and mark ANY-652 Done only after completion is verified.

## Plan self-review

All spec sections map to tasks: authentication/limits4; client selection/secrets2;
truthful historical data1/3/6; conflicts/receipts3; recovery/fencing5;
schema/operations3/6. Interfaces use one request/report vocabulary, the same
source identity and explicit per-item transactions. Review Focus cases have
owning tests. No credentials, paid calls or website integration are required.
