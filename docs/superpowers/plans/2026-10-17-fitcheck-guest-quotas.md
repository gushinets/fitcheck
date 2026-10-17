# ANY-651 Guest Sessions and Quotas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable one successful pre-registration demo per 24-hour guest session, enforce durable product/spending limits, and safely claim guest data into a verified account.

**Architecture:** Extend the existing FastAPI/PostgreSQL API and durable worker. Separate product reservations from conservative physical-call budgets; use the existing immutable profile/result storage and transfer primitive behind authenticated application services. Version new job envelopes without invalidating queued v1 account jobs.

**Tech Stack:** Python 3.12+, FastAPI/Pydantic, SQLAlchemy, PostgreSQL 17/Alembic, existing OpenAI/LiteLLM boundary, pytest, generated OpenAPI/TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-17-fitcheck-guest-quotas-design.md` (approved in chat 2026-10-17; spec commit `4fa5893`).

## Global Constraints

- Guest: 1 successful analysis, 5 successful suggestions, 10 successful extractions per absolute 24-hour session; max 1 queued/running job.
- Verified account: UTC-day limits 20 analyses including reanalysis, 50 suggestions, 100 extractions; max 2 active jobs.
- Guest issuance: 3/IP/hour and 10/IP/day. Guest jobs: 5/guest/minute and 30/IP/15 minutes. Guest extraction: 10/guest/minute and 60/IP/15 minutes. Preserve account rate rules.
- Physical calls across all attempts of one job: analysis 8, suggestions 4. Total input+output token ceilings: 40 000 / 10 000. Job USD ceilings: 0.02 / 0.005.
- Additional USD ceilings: guest session 0.05; account/UTC-day 0.50; deployment/UTC-day 10.00. Settings validate bounded positive values; money uses Decimal, never binary float.
- Product quota: reserve atomically, consume on success, release on terminal failure. Technical retries reuse the reservation; financial uncertainty never refunds estimated exposure.
- Session cookies, Origin/CSRF, explicit identity selection, no ownerId/guestId trust, no fallback after invalid selected identity. Existing account history/annotations stay account-only.
- Claim requires both sessions/CSRFs, verified account and Idempotency-Key. Copy guest profile only into an empty account; preserve immutable snapshots and existing account settings.
- Add only migration `0008_guest_quotas`; freeze `0001`–`0007`. No Redis, billing, paid canaries, real `.env` edits or website integration.
- Keep v1 job decoding and server-default technical budgets for legacy jobs. Preserve exact-head migration checks and document coordinated API/worker rollout.
- Execute implementation in an isolated worktree. Do not push/deploy while reviewing this plan. No Linear comments/messages; status changes can reflect actual progress.

## Review Focus

1. A browser holds invalid account and valid guest cookies: a failed selected account identity must not silently spend guest quota (Task 2).
2. Midnight or guest expiry occurs while a job is running: settlement addresses the original reservation; no fresh-window refund or extra provider send (Tasks 3–5).
3. A worker crashes after budget reservation or sends a request whose usage is unknown: recovery cannot reset call counts or treat cost as zero (Task 4).
4. Claim and account deletion race with a completion: no mixed ownership, erased data resurrection or orphan financial links (Tasks 5–6).
5. A v1 account job already queued before migration executes after 0008: it still works with durable limits and does not acquire retroactive product charges (Tasks 4–5).

## File/Responsibility Map

- `guests/types.py`, `guests/sessions.py`, `guests/claim.py`: authenticated guest principal, cookie sessions and transactional claim orchestration.
- `quotas/policy.py`, `quotas/service.py`, `quotas/errors.py`: settings-derived limits, product reservation lifecycle and typed failures.
- `budgets/types.py`, `budgets/tokens.py`, `budgets/service.py`: conservative call bounds and persisted physical-call budget admission/settlement.
- `storage/guest_access.py`, `storage/quota_operations.py`, `storage/budgets.py`: ORM schema only; register models in `storage/models.py`.
- `storage/guest_repository.py`, `storage/quota_repository.py`, `storage/budget_repository.py`: caller-owned SQL primitives with explicit locking; no nested engine creation.
- `api/guests.py`, `api/quota.py`, `api/dependencies.py`: cookie/CSRF adapters, identity selection and account-only boundaries.
- Existing admission/envelope/execution, provider ledger, queue/publication, auth deletion and ownership modules receive integration changes, without duplicating the pipeline.
- `contracts/guests.py`, `contracts/quotas.py`: guest/quota DTO additions; existing public resource names remain importable for compatibility.
- Unit tests exercise policy/DTO/token/error behavior; PostgreSQL tests prove races, FK/deletion behavior and HTTP isolation.

## Execution and Test Conventions

Work from the implementation worktree. Create `backend/compose.any651-test.yaml` only if the default test port is occupied; otherwise use project `fitcheck-any651` with the existing compose file. Never stop another project's containers. `FITCHECK_TEST_DATABASE_URL` points only to its disposable `fitcheck_test` database. Unit tests use an environment with `PYTHON_DOTENV_DISABLED=1`, no production FITCHECK variables or provider keys; importing LiteLLM must not load local dotenv secrets.

Commands below run from `backend/` with its locked environment:
`uv run --locked pytest ... -q` for unit tests; add `-m integration` for PostgreSQL tests. The configured addopts already excludes integration unless explicitly selected. Every Task's RED step runs its named tests before implementation; GREEN runs the same tests plus the covering existing tests listed. Record the actual first failure and final result in task evidence.

## Task 1: Policy, storage and migration

**Files:** Create `quotas/{__init__,policy,errors}.py`, `budgets/{__init__,types}.py`, `guests/{__init__,types}.py`, `storage/{guest_access,quota_operations,budgets}.py`, `contracts/{guests,quotas}.py`, `migrations/versions/0008_guest_quotas.py`; modify `config.py`, `storage/models.py`, `contracts/resources.py`, `api/errors.py`, `jobs/errors.py`, `llm/errors.py`, `.env.example`. Paths in this plan are relative to `backend/src/fitcheck_backend/` unless explicitly migration/test/docs paths.

**Interfaces:**
- `QuotaPolicy.from_settings(settings: Settings) -> QuotaPolicy`; `limits(mode: Literal['account','guest']) -> OperationLimits` with analysis/extraction/suggestions/max_active_jobs.
- `AccessIdentity` contains mode, owner_id, session_id, expires_at and optional user_id; never contains raw cookie/token.
- `QuotaError(code: Literal['quota_exceeded','budget_exceeded'], *, retry_after: int | None = None)` maps admission to 429 with safe envelope.
- `CallBounds(input_tokens: int, output_tokens: int, usd: Decimal, rate_version: str)` is the upper exposure for one physical send.
- `GuestSessionRow`: owner FK, unique token digest, expires_at/revoked_at/created_at. `GuestClaimReceipt`: unique `(account_owner_id,idempotency_key)`, guest owner, request hash, claimed_count, profile_imported.
- `ExtractionReservation`: UUID operation_id, owner, product bucket, state reserved/consumed/released, expiry/created/updated timestamps. Persist a 120-second extraction lease; reserve/reap before network work, and reject late successful settlement after expiry.
- `BudgetWindow`: scope deployment/owner/job, stable scope_key, fixed window_start, expiry, immutable limits, exposure_tokens/exposure_usd/call_count. `CallReservation`: provider_call_id, original owner/job/window references, reserved bounds, settled/unknown state. Window counter changes happen only in repository transactions.

- [ ] **RED tests:** add `tests/quotas/test_policy.py`, `tests/test_guest_contracts.py`, and `tests/integration/test_guest_quota_migration.py`: assert all exact defaults above; reject zero/negative/bool/nonfinite budgets; no plaintext session secret columns; duplicate session digests/claim keys rejected; product and money capacities cannot exceed limits; timezone-aware fields and FK ownership enforced. Upgrade 0007→0008 preserves fixture results.
Example assertions in `tests/quotas/test_policy.py`:
```python
def test_approved_defaults():
    policy = QuotaPolicy.from_settings(Settings())
    assert policy.limits('guest').analysis == 1
    assert policy.limits('guest').max_active_jobs == 1
    assert policy.limits('account').analysis == 20
    assert policy.limits('account').max_active_jobs == 2
```
- [ ] Run the named tests; verify failures identify absent policy/models/migration rather than missing test infrastructure.
- [ ] Implement additive schema and settings. Use NUMERIC(24,12) money, bounded integers, named checks/indexes, immutable window limit snapshots. Product reservations retain the existing quota tables for jobs. Claim and budget FK/delete rules must preserve anonymous deployment totals while deleting personal links. Add error handlers/DTO exports.
- [ ] **GREEN:** named tests plus `tests/test_storage_metadata.py`, `tests/test_storage_payloads.py`, migration/package tests and full OpenAPI validation after regenerating its interim artifact.
- [ ] Commit `feat: add guest quota policy and storage` with only this task's files.

## Task 2: Verified guest sessions and identity-aware reads

**Files:** Create `guests/sessions.py`, `storage/guest_repository.py`, `api/guests.py`, `tests/auth/test_guest_crypto.py`, `tests/integration/test_guest_sessions_http.py`; modify `auth/crypto.py`, `auth/rate_limit.py`, `api/{dependencies,runtime,app,jobs,history}.py`, `jobs/status.py`, `history/service.py`, `contracts/{operations,openapi}.py`, `tests/auth/test_website_only.py`.

**Interfaces:**
- `GuestSessions(engine, crypto, policy, clock)`; `issue_or_reuse(raw_cookie: str | None, *, client_ip: str) -> IssuedGuestSession`; `resolve(raw_cookie: str, *, allow_claim_receipt: bool = False) -> AccessIdentity`; `csrf(raw_cookie: str) -> str`.
- `IssuedGuestSession` returns raw cookie only to HTTP adapter plus DTO/identity; token is repr-hidden. Repository stores digest only.
- `resolve_identity(request: Request, mode: Literal['account','guest'] | None = None) -> AccessIdentity`; `validate_identity_mutation(request, identity) -> None` uses the selected cookie's CSRF.
- `GuestSessions.require_active(session: Session, identity: AccessIdentity, now: datetime, *, allow_claim_receipt=False) -> Guest` repeats expiry/revocation/claim validation inside the transaction.
- `POST /v1/guest-sessions` uses existing bootstrap and returns 201; reuse preserves token/TTL/remaining credits. Admission remains disabled for guests until Tasks 3–5 integrate it.

- [ ] **RED tests:** request without bootstrap/Origin fails; TTL equals 86400s; reuse does not renew; raw token not stored; forged/expired/revoked/claimed token rejected. Two guests cannot read each other's jobs/detail. Both cookies present obey selector/default; invalid account plus valid guest yields account failure without fallback. Unverified account still fails. Existing account-only history/annotations reject guests.
Name the boundary tests `test_guest_reuse_keeps_absolute_expiry`, `test_selected_invalid_account_has_no_guest_fallback`, and `test_foreign_guest_job_returns_404`; assert unchanged expiry/remaining, 401, and 404 respectively. In the last test, neither foreign job state nor result ID may appear in the response.
- [ ] Run `tests/auth/test_guest_crypto.py` and `tests/integration/test_guest_sessions_http.py` RED.
- [ ] Implement independent HMAC scope, cookie naming/options and HMAC IP creation limits, including concurrent issuance. Modify only job/detail reads to accept identity; service checks session inside the read transaction. No guestId HTTP parameter. Keep account-only `verified_principal` consumers intact.
- [ ] **GREEN:** named tests plus auth HTTP/isolation, jobs HTTP and history HTTP suites. Check disabled auth returns existing safe 503 and bearer headers retain rejection semantics.
- [ ] Commit `feat: add verified guest sessions and identity selection`.

## Task 3: Atomic product quotas and synchronous extraction

**Files:** Create `quotas/service.py`, `storage/quota_repository.py`, `api/quota.py`, `tests/quotas/test_windows.py`, `tests/integration/{test_quota_reservations,test_guest_extraction_http}.py`; modify `api/{runtime,app,extraction}.py`, `extraction/service.py`, `auth/rate_limit.py`, contracts and settings docs/examples.

**Interfaces:**
- `QuotaRepository(session)`; `reserve_job(owner_id: UUID, job_id: UUID, operation: str, policy: QuotaPolicy, now: datetime) -> QuotaReservation`; `settle_job(job_id: UUID, *, success: bool, now: datetime) -> bool` (true only for first settlement).
- `reserve_extraction(owner_id, operation_id, policy, now) -> ExtractionReservation`; `settle_extraction(operation_id, *, success, now) -> bool`; `reap_extractions(now, *, limit=100) -> int`.
- `QuotaService.get(identity: AccessIdentity) -> QuotaResource` returns analysis-compatible remaining/resetsAt plus per-operation limits/reserved/remaining, TTL, registrationRequired and active counts.
- `ExtractionService.extract(identity, body, client_ip)` reserves in a short transaction, releases DB locks during existing network/parsing work, then settles in a new identity-checked transaction.

- [ ] **RED tests:** limit=1 with two independent DB sessions admits exactly one reservation; repeat settlement does nothing; released quota can be reused; success cannot consume twice; failure does not reset IP rate buckets. Original window settles correctly across UTC midnight. Pending extraction returns reserved credit only after its lease expires, and late settle cannot consume a released reservation.
- [ ] **RED HTTP tests:** URL/text share guest quota; missing or wrong selected CSRF fails; account limits remain intact; quota output exposes reserved versus consumed; DB outage fails before external extraction. Claim sees pending extraction as busy (Task 6 will exercise end-to-end).
Race assertions in `test_one_remaining_slot_has_one_winner`: use two independent PostgreSQL connections and a barrier, collect results, then assert exactly one admitted reservation, `reserved == 1`, `consumed == 0`, and `remaining == 0`. `test_settlement_uses_original_midnight_window` asserts the previous-day bucket changes while next-day counters stay zero.
- [ ] Run these tests RED, then implement atomic conditional updates and deterministic locking. Reaper processes at most100 rows using skip-locked; quota/admission first run the bounded reaper. No recurring scheduler.
- [ ] **GREEN:** named tests plus existing extraction/network/field/HTTP suites and storage concurrency tests. Confirm network fake call count stays zero after quota denial.
- [ ] Commit `feat: enforce product quotas and extraction reservations`.

## Task 4: Durable physical-call/token/USD budgets

**Files:** Create `budgets/{tokens,service}.py`, `storage/budget_repository.py`, `tests/budgets/test_bounds.py`, `tests/integration/test_persistent_budgets.py`; modify `storage/provider_repository.py`, `llm/{gateway,types,context,litellm_adapter,runtime,policy}.py`, `auth/access.py`, corresponding provider/LLM tests, `pyproject.toml`/`uv.lock` only if a direct tokenizer dependency is necessary.

**Interfaces:**
- `upper_call_bounds(*, messages: list[dict], response_schema: dict | None, model: str, max_output_tokens: int) -> CallBounds`; accepted model is the pinned gpt-6-luna policy, unsupported modes fail before send.
- `BudgetRepository(session).reserve(attempt: ProviderAttempt, bounds: CallBounds, *, policy: QuotaPolicy, now: datetime) -> UUID` returns provider call ID; atomically creates started ledger row and all three scope reservations.
- `settle(call_id: UUID, *, reply: ProviderReply, outcome: str, now: datetime) -> None` retains uncertainty conservatively and is idempotent; same-call replay cannot restore exposure.
- `ProviderLedger.start(attempt, *, bounds: CallBounds) -> UUID`; `finish` keeps existing accounting fields and delegates financial settlement in its transaction. Update fakes to accept bounds explicitly.

- [ ] **RED tests:** concurrent owners compete for deployment ceiling with exactly one allowed call; persisted job call8/4 cap includes audit/transport and a second worker attempt. Simulated crash between committed reservation and network send retains exposure; unknown/cancelled/process_lost does not release it. Known usage releases only proven excess; repeated finish is idempotent. Rejected reservation yields zero provider sends and stable budget_exceeded.
- [ ] **Bounds tests:** Cyrillic/emoji/schema/framing and maximum supported input cannot be undercounted; context above supported pricing threshold and unsupported tier/model fail before send. Use an explicit supported tokenizer plus a conservative UTF-8 byte ceiling for content/schema and bounded request framing; if tokenizer/model resolution cannot provide an upper bound, fail closed. Token policy counts input+output, output already includes reasoning. Worst-case pricing assumes no cache discount and uses the highest supported input subdivision rate, including cache writes; never invoke estimate_openai_cost with invented actual usage to claim measured spend.
Name budget regressions `test_crash_after_reserve_retains_exposure`, `test_unknown_reply_never_refunds_money`, `test_recovery_keeps_eight_call_cap`, and `test_parallel_owners_share_deployment_cap`. Assert unknown exposure stays equal to the reservation; a ninth analysis physical send is rejected with `budget_exceeded`; the fake adapter records at most eight sends across both leases; two competing owners cannot both exceed the shared ceiling.
- [ ] Run named tests RED. Implement shared financial admission for every production backend provider send, never merely in-memory CallBudget. Set provider request Standard tier consistently with policy. Preserve actual-rate/unknown accounting independently of reservation ceilings.
- [ ] Enforce lock order across lifecycle code: owners in UUID order → identity/session rows → jobs in UUID order → quota/budget windows in stable `(scope,scope_key,window_start)` order → reservation/provider rows. All financial code acquires its owner/job before windows; terminal job recovery marks unknown and retains exposure without acquiring financial windows after provider rows. Account deletion first locks its affected owner graph, then new window/reservation rows, before existing cascades; it never decrements anonymous deployment totals.
- [ ] **GREEN:** named tests plus gateway, adapter, pricing, provider execution/storage/usage-basis and auth deletion races. Verify legacy queued jobs atomically obtain safe default technical limits before first send without product reservation backfill.
- [ ] Commit `feat: enforce durable provider spending budgets`.

## Task 5: Guest job admission, versioned envelopes and terminal settlement

**Files:** Modify `jobs/{admission,envelope,execution,status}.py`, `api/jobs.py`, `storage/{job_publication,job_queue}.py`, `worker/runtime.py`, `analysis/service.py`; create `tests/integration/{test_guest_jobs_http,test_guest_job_recovery}.py`; extend `tests/jobs/{test_envelope,test_execution}.py`, worker recovery/publication/admission tests.

**Interfaces:**
- Preserve `AnalysisEnvelope` v1 decoder. Add `AnalysisEnvelopeV2(envelopeVersion=2, mode, profileRevision, profile, vacancy, locale, memory, versions, limits)` normalized independently of the public request DTO; `decode_envelope` accepts both versions and `FrozenJobExecutor` consumes normalized fields.
- `JobAdmission.start_analysis(..., identity: AccessIdentity, request: AccountAnalysisStart | GuestAnalysisStart, idempotency_key, client_ip)` validates explicit mode, frozen profile and session before creating v2. Maintain compatibility adapters for current internal account call sites; the HTTP path always supplies a checked identity.
- `start_suggestions` and `reanalyze` use the same account/guest quota service; reanalysis remains verified account-only. All new jobs freeze bounded limits. Guest analysis persists immutable profile revisions with create/update repository helpers and empty calibration memory.
- `finish_job(session, job, *, success: bool, now)` centralizes terminal product settlement; publication, exhausted claim attempts and expired lease terminal failure all call it within their existing transaction.

- [ ] **RED tests:** one guest/demo, same-key replay and changed-payload conflict, two simultaneous starts create one job, 1/2 active limits, submitted mode cannot select somebody else's session. Suggestions obey their independent quota. Account reanalysis consumes analysis credit. Profile/body changes after admission do not change the frozen guest input.
- [ ] **Expiry/recovery tests:** success consumes once; terminal failure releases; retry/recover does neither until terminal; old lease cannot publish/settle; midnight settles original bucket; no new physical call starts after guest/session expiry. Already-sent replies remain accounted and expiry never restores guest access.
Name lifecycle regressions `test_guest_demo_replay_has_one_reservation`, `test_terminal_error_returns_demo_once`, `test_old_lease_cannot_settle_new_attempt`, `test_expired_guest_cannot_send_again`, and `test_queued_v1_account_job_survives_0008`. Assertions: same replay ID and one row; released balance exactly1; stale publish returns false/no counter change; zero new fake sends after expiry; old job publishes unchanged snapshot without retroactive product quota.
- [ ] Run named tests RED; implement shared admission order and all terminal hooks, respecting Task4 lock order. Job completion, analysis snapshot/FK persistence and product settlement commit or rollback together.
- [ ] **GREEN:** all jobs/worker unit and PG suites, existing ANY-650 reanalysis/history tests, and v1 compatibility test created before Task1 migration. Claim/delete cannot race stale guest admission because owner state is rechecked under lock.
- [ ] Commit `feat: support quota-controlled guest analysis jobs`.

## Task 6: Transactional guest claim and empty-account profile import

**Files:** Create `guests/claim.py`, `tests/integration/{test_guest_claim_http,test_guest_claim_races}.py`; modify `api/guests.py`, `api/dependencies.py`, `api/middleware.py`, `storage/{guest_repository,ownership}.py`, `auth/access.py`, `contracts/{guests,resources}.py`, account deletion tests.

**Interfaces:**
- `GuestClaimService.claim(*, account: Principal, guest: AccessIdentity, idempotency_key: str) -> GuestClaimResult`; internal repository uses active sessions and returns a stored receipt for same-account/key/guest replay.
- `transfer_guest_analyses` remains caller-owned and preserves terminal graph semantics. Do not move guest budget windows into account windows or release deployment exposure.
- Add `X-Guest-CSRF-Token` to exact CORS headers. Endpoint validates both proofs independently. Guest session after claim can resolve only for receipt replay to the same verified account, never ordinary operations.

- [ ] **RED tests:** wrong/missing either cookie or CSRF, expired guest, unverified account, forged ownerId, and second-account claim fail. Same receipt replay returns same count/profileImported; reused key with another guest conflicts. Pending jobs/extraction or job-key collision rolls back all ownership/profile/receipt changes.
- [ ] **Race tests:** two accounts claim one guest; claim versus late completion; claim versus account deletion; two claims into one empty account. Assert one winner/receipt/profile revision, no mixed FK graph, no guest resurrection, no added account quota. Existing populated account profile/preferences/draft and all historical snapshots remain byte-for-byte unchanged.
Name claim regressions `test_two_accounts_claim_one_guest`, `test_empty_account_receives_guest_profile`, `test_populated_profile_is_not_overwritten`, `test_pending_extraction_blocks_claim`, and `test_claim_delete_race_cannot_resurrect_data`. Assert one owner/receipt, first revision equals guest profile only for empty account, existing revision/payload unchanged otherwise, 409 with unchanged graph while busy, and no personal rows remain after successful deletion.
- [ ] Run named tests RED; implement stable owner graph locks, revalidation, transfer, first account profile creation from latest guest revision, receipt and claimed marker in a single UoW. Existing immutable key collision returns409, with no destructive rename or incomplete retry promise.
- [ ] **GREEN:** named tests, all ownership/auth deletion/race/history clear suites, FK metadata drift, and technical budget totals after deletion/claim. Deletion removes session/receipt/personal reservation links but retains anonymous deployment exposure.
- [ ] Commit `feat: claim guest results and profile into accounts`.

## Task 7: Contracts, complete verification and operational handoff

**Files:** Modify `backend/README.md`, root `README.md`, backend/root `.env.example` only for non-secret documented settings, `.github/workflows/ci.yml` only if new test selection/build checks require it, `contracts/fitcheck.openapi.json`, `lib/backend/generated/schema.ts`, `lib/backend/client.test.ts`, OpenAPI contract tests. Create `docs/deployments/2026-10-17-any-651-guest-quotas.md` as a local validation/rollout record clearly distinguishing executed checks from pending deployment.

**Interfaces:** Preserve all public operation IDs and account mode defaults. Document guest/quota error codes, response fields, CSRF/selector behavior, return-versus-financial-retention policy, ceilings and all retry/claim409 behavior. No server ledger internals in client DTOs.

- [ ] Add failing contract/client tests for guest cookie security definitions, mode selectors, three implemented guest/quota routes, claim CSRF header, extended quota DTO and typed429 errors. Confirm planned ANY-652 stays planned and account-only history never advertises guest access.
Add `test_guest_contract_security_and_quota_errors`: assert guest claim declares both cookie proofs and `X-Guest-CSRF-Token`; all guest operations carry implemented metadata; `/v1/history` security remains account-only; `/v1/import-jobs` stays planned; quota remaining is nonnegative and typed429 exposes no SQL/provider details.
- [ ] Regenerate OpenAPI using `uv run --locked python scripts/export_openapi.py`; from repo root generate types with `node scripts/generate-backend-types.mjs`. Update implemented-owner assertions to include ANY-651.
- [ ] Run full isolated backend checks: `PYTHON_DOTENV_DISABLED=1 uv run --locked pytest -m 'not integration' -q`; disposable PostgreSQL `uv run --locked pytest -m integration -q`; migration `check`; OpenAPI `--check`. Never read production `.env` into these test commands.
- [ ] From root run `node scripts/generate-backend-types.mjs --check`, `node node_modules/typescript/bin/tsc --noEmit`, all Vitest tests, ESLint and production webpack build. Run both `backend/Dockerfile` and `backend/Dockerfile.worker` image builds and schema/startup smoke using disposable DB only; no paid provider requests.
- [ ] Before declaring complete, invoke verification-before-completion and request a fresh whole-branch review using requesting-code-review; fix verified blocking findings with targeted RED→GREEN tests and repeat affected checks. Record results and remaining limitations.
- [ ] Commit verified implementation/docs/artifacts. Keep deployment pending until the exact reviewed commit is integrated/pushed through the chosen finishing workflow; do not treat manual deployment instructions or autodeploy toggle state as runtime evidence.
- [ ] For an authorized actual dev rollout: pause admission on the old pinned image; drain/inspect frozen jobs without deleting them; apply0008 once; deploy matching API and worker; verify schema/health and non-paid guest bootstrap/quota/access isolation; then enable admission. Save exact commit, CI URL and API/worker deployment evidence. TLS webhook failure needs manual deploy or administrator repair, never disabling SSL verification.
- [ ] Update ANY-651 status according to verified scope; state explicitly whether completion is local or deployed. Preserve UI work in ANY-579/653. Stop only the task-owned disposable PostgreSQL; finish with `git diff --check` and a clear working-tree report.

## Plan Self-Review

- [x] Spec coverage mapped: identity2; quotas/extraction3; token/cost/call budgets4; admission/snapshots/settlement5; claim/profile6; migrations/contracts/deletion/verification1,4,6,7.
- [x] Five Review Focus cases each have a named owner and concrete assertions.
- [x] Interfaces use the same AccessIdentity, CallBounds, policy and settlement names between tasks; compatibility adapters preserve existing account internal callers.
- [x] Explicit terminal paths, legacy jobs, unknown usage and migration exact-head rollback limits are included; no placeholder or unowned subsystem.
- [x] Plan changes no product code and starts execution only after user review and execution-method selection.
