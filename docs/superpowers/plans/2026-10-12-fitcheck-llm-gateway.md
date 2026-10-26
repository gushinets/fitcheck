# FitCheck LLM Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Перенести Fit-анализ и подсказки навыков в проверяемый server-owned gateway с учётом каждого физического вызова.

**Architecture:** Прикладные сервисы читают owner-scoped profile/memory и вызывают structured executor. PydanticAI валидирует output через собственный model adapter, который обращается только к ProviderGateway/LiteLLM. Ledger коммитится отдельно от будущей публикации анализа; публичные job endpoints остаются planned до ANY-649.

**Tech Stack:** Python 3.12+, Pydantic 2, pydantic-ai-slim, LiteLLM SDK, SQLAlchemy 2, PostgreSQL, Alembic, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-12-fitcheck-llm-gateway-design.md`

## Global Constraints

- Только сайт; standalone backend, без platform imports/runtime и LiteLLM Proxy.
- Server-owned DeepSeek policy использует текущую модель `deepseek-v4-flash`; модель и prompts не выбираются через DTO.
- Два semantic attempts и два transport attempts; hard cap анализа — восемь физических вызовов, suggestions — четыре.
- Timeout физической попытки — максимум 45 секунд; overall deadline анализа — 120 секунд, suggestions — 60 секунд.
- Generation output limit — 1200 tokens, audit — 1000, suggestions — 500. Hidden retries/fallback и внешняя телеметрия отключены.
- `verdictThreshold: 70`; score ≥ 70 → GO. Monthly income исключён.
- Memory — последние десять принадлежащих owner анализов, порядок created_at/id DESC.
- Ledger не содержит сырой output/input, ключи, profile, vacancy или memory; неизвестные usage/cost остаются null.
- Существующая initial migration 0001 сохраняется; новая additive 0002 не требует reset.
- Jobs/worker — ANY-649; history publication — ANY-650; guest admission — ANY-651; UI switch — ANY-653.

## Review Focus

- Owner с одинаковыми timestamps истории получает стабильные десять записей без чужих annotations — Task 1.
- Исчезнувшая profile revision или чужой job отклоняется до платного вызова — Task 5.
- Provider успешен, но процесс не может завершить ledger: результат не возвращается, автоматического повторного вызова нет — Task 3.
- Audit correction и transport retries вместе не превышают общий cap/deadline — Task 4.
- Старые JSON payloads и незаданный ключ не ломают storage/API startup — Tasks 2 и 5.

---

### Task 1: Ledger metadata и server-owned calibration memory

**Files:** Modify `backend/src/fitcheck_backend/storage/accounting.py`; create `backend/migrations/versions/0002_provider_call_metadata.py`, `backend/src/fitcheck_backend/storage/provider_repository.py`, `backend/src/fitcheck_backend/storage/calibration_repository.py`; test `backend/tests/integration/test_llm_storage.py`; update migration-head assertions in existing storage tests.

**Interfaces:**
- `CalibrationEntry(job_title: str, predicted_score: int, corrected_score: int | None, note: str | None)` — frozen dataclass.
- `get_calibration(session: Session, owner_id: UUID) -> list[CalibrationEntry]`.
- `ProviderAttempt` — frozen dataclass with owner/job IDs, operation UUID, physical/semantic/transport indices, operation name, provider/model and prompt/schema/policy versions.
- `ProviderLedger(engine).start(attempt: ProviderAttempt) -> UUID` and `.finish(call_id: UUID, *, state: str, input_tokens: int | None, output_tokens: int | None, cost: Decimal | None, currency: str | None, latency_ms: int, error_code: str | None) -> None` each own a short committed transaction.

- [x] Write failing integration tests `test_memory_is_owner_scoped_and_stable_last_ten` (tied timestamps; foreign annotation excluded), `test_attempt_commits_survive_caller_rollback`, `test_old_provider_rows_upgrade_with_nullable_metadata`, `test_ledger_rejects_foreign_job`. Assert eight metadata fields: prompt/schema/policy versions, semantic/transport indices, latency_ms plus existing operation/physical attempt; no payload columns.
- [x] Run `cd backend && uv run --locked pytest -m integration tests/integration/test_llm_storage.py -q` with disposable `FITCHECK_TEST_DATABASE_URL`; expect missing repository/schema failures.
- [x] Add nullable metadata columns/checks in 0002 and matching model; use existing owner/job FK and explicit repository precheck. Memory uses owner-filtered analyses and owner-filtered LEFT JOIN annotations, LIMIT 10 and descending created_at/id. Validate stored DTOs before constructing bounded calibration entries.
- [x] Run new integration tests and existing storage/bootstrap/drift/deletion tests; expect all pass and unchanged anonymization semantics.
- [x] Commit `feat: add provider attempt metadata and calibration repositories`.

### Task 2: Pure domain parity, prompts and output contracts

**Files:** Create `backend/src/fitcheck_backend/analysis/{__init__,types,currency,grounding,prompt,normalize,schemas}.py`, `backend/src/fitcheck_backend/skill_suggestions/{__init__,prompt,normalize,schemas}.py`; modify `backend/src/fitcheck_backend/contracts/domain.py`; tests under `backend/tests/analysis/`, `backend/tests/skill_suggestions/`, existing storage payload tests.

**Interfaces:**
- `AnalysisInput(profile: FreelancerProfile, vacancy: Vacancy, locale: Locale, memory: list[CalibrationEntry])`.
- `compare_hourly_rate(profile: FreelancerProfile, vacancy: Vacancy) -> Literal['no_hourly_budget','unknown_currency','conversion_required','unknown_hourly_ceiling','within_budget','above_budget']`.
- `build_strength_evidence(value: AnalysisInput) -> list[StrengthFact]`; fact fields `id`, `text`, `profile_fields`, `task_fields`.
- `AnalysisPrompt(instructions: str, input: str, strength_facts: list[StrengthFact])`; `build_analysis_prompt(value: AnalysisInput) -> AnalysisPrompt`.
- `RawFitAnalysis` has existing report fields with strengths as ID strings; `GroundingAudit(supported: bool, unsupported_claims: list[str])`.
- `normalize_analysis(raw: RawFitAnalysis, evidence: list[StrengthFact]) -> FitAnalysis` rejects duplicate/unknown IDs and replaces IDs with server-owned text/evidence.
- `build_suggestion_prompt(specialization: str, locale: Locale) -> tuple[str, str]`; `normalize_skills(values: list[str]) -> list[str]` trims, deduplicates case-insensitively and retains first ten.

- [x] Port assertions from TS currency/grounding/prompt/service/schema tests. Add `test_verdict_threshold_boundaries` with `(69,'NO_GO'),(70,'GO')`, `test_basic_skill_cannot_be_strength`, `test_unknown_or_duplicate_strength_id_rejected`, `test_fixed_budget_is_not_hourly`, `test_income_not_in_prompt`, `test_legacy_analysis_without_new_fields_roundtrips`.
- [x] Run `uv run --locked pytest tests/analysis tests/skill_suggestions -q`; expect missing module/contracts failures.
- [x] Implement pure ports preserving RU/EN text and safe evidence semantics. Add optional `verdict_threshold` (integer 0–100) and nullable `fit_condition` (max 300 chars) to FitAnalysis; new results set threshold 70 and omit condition. Retain old missing-field serialization and snapshot schema v1. Add no competition scoring or condition generation.
- [x] Run domain and storage payload tests; expect all pass, including old fixture byte-shape compatibility.
- [x] Commit `feat: port grounded fit analysis domain and skill suggestions`.

### Task 3: Server policy and physical-attempt gateway

**Files:** Create `backend/src/fitcheck_backend/llm/{__init__,policy,types,errors,gateway,litellm_adapter}.py`; modify `backend/src/fitcheck_backend/config.py`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/.env.example`; tests `backend/tests/llm/test_gateway.py`, `test_policy.py`, `test_config.py` and integration ledger tests.

**Interfaces:**
- `ProviderPolicy` frozen dataclass includes versions/model, operation max_tokens, transport/semantic budgets, physical cap and deadlines; `analysis_policy()` / `suggestion_policy()`.
- `CallBudget(max_calls: int, deadline: float, clock: Callable[[], float])` tracks shared operation usage; `.admit() -> tuple[int, float]` returns physical index and remaining time or raises safe `LlmError`.
- `LlmError(code: Literal['timeout','rate_limit','invalid_output','upstream','service_unavailable'])` never includes raw provider exception/input.
- `ProviderReply(content: str, input_tokens: int | None, output_tokens: int | None, cost: Decimal | None, currency: str | None)`.
- Async `LiteLlmAdapter.complete(*, messages: list[dict], policy: ProviderPolicy, max_tokens: int, timeout: float) -> ProviderReply`; lifecycle `.aclose()`.
- Async `ProviderGateway.complete(*, context: OperationContext, messages: list[dict], semantic_attempt: int, operation: str, max_tokens: int) -> GatewayReply`; reply includes provider content and ledger call ID for validation status. `OperationContext` carries immutable owner/job/operation IDs, policy and shared CallBudget.

- [x] Write failing tests: two transport attempts produce two rows; `num_retries=0` and nested SDK retries disabled; 401 no retry; timeout/network/429/5xx bounded retries; Retry-After never crosses deadline; start-ledger failure causes zero calls; finish-ledger failure causes one call and no returned success; null unknown cost preserved; key/raw exception redacted.
- [x] Run `uv run --locked pytest tests/llm/test_gateway.py tests/llm/test_policy.py -q`; expect missing gateway failures.
- [x] Check current official LiteLLM/PydanticAI docs and installed reference APIs before adapter coding. Add locked `litellm` and `pydantic-ai-slim` through `uv add`, selecting only extras needed by adapter. Implement gateway with separate short DB transactions, no transaction held during network/backoff, injected adapter/clock/sleep for deterministic tests. Add optional SecretStr `deepseek_api_key`; use server policy model, not a request override. Disable content telemetry/callbacks and fallback paths.
- [x] Run gateway unit/integration tests, settings redaction tests and wheel smoke tests. Verify production dependency resolution, timeout cancellation and client close, rather than only mock signatures.
- [x] Commit `feat: add accounted DeepSeek provider gateway`.

### Task 4: PydanticAI executor and semantic grounding retries

**Files:** Create `backend/src/fitcheck_backend/llm/structured.py`, `backend/src/fitcheck_backend/analysis/executor.py`, `backend/src/fitcheck_backend/skill_suggestions/executor.py`; tests `backend/tests/llm/test_structured.py`, `backend/tests/analysis/test_executor.py`, `backend/tests/skill_suggestions/test_executor.py`.

**Interfaces:**
- Gateway-backed PydanticAI model adapter uses Task 3 `ProviderGateway.complete`; no direct provider SDK call.
- Async `AnalysisExecutor(gateway).run(context: OperationContext, value: AnalysisInput) -> FitAnalysis` performs generation, normalization and report audit.
- Async `SuggestionExecutor(gateway).run(context: OperationContext, specialization: str, locale: Locale) -> list[str]` validates/normalizes suggestions.

- [x] Write tests `test_invalid_json_gets_one_semantic_correction`, `test_unsupported_claim_requires_regeneration`, `test_failed_audit_never_returns_analysis`, `test_shared_eight_call_cap_includes_audits_and_transport_retries`, `test_deadline_stops_next_semantic_attempt`, `test_suggestions_four_call_cap`, `test_schema_feedback_is_data_not_prompt_instruction`. Assert bounded attempt indices, usage retained for invalid outputs and failed ledger validation state.
- [x] Run executor tests; expect missing adapter/executor failures.
- [x] Implement PydanticAI typed output and validators with total two semantic attempts. Choose supported structured mode from current docs, preserve DeepSeek JSON-object transport and disabled thinking, and do not add a conflicting second schema owner. Audit only label/summary/risks against original profile/task. Final domain/DTO validation precedes success; validation rejection updates relevant physical ledger row(s) without erasing usage. Correction feedback is bounded and treated as untrusted data.
- [x] Run complete mock conversation tests through the real PydanticAI adapter, not bypassing it with a prevalidated DTO. Verify eight/four caps and overall time budgets including audit correction.
- [x] Commit `feat: validate structured analysis and bounded grounding retries`.

### Task 5: Owner-scoped application services and lifecycle

**Files:** Create `backend/src/fitcheck_backend/analysis/service.py`, `backend/src/fitcheck_backend/skill_suggestions/service.py`, `backend/src/fitcheck_backend/llm/runtime.py`; tests `backend/tests/integration/test_analysis_service.py`, `backend/tests/integration/test_suggestion_service.py`, `backend/tests/llm/test_lifecycle.py`.

**Interfaces:**
- `AnalysisResult(analysis: FitAnalysis, snapshot: AnalysisSnapshot)` frozen dataclass.
- Async `AnalysisService(engine, executor, policy).analyze(*, owner_id: UUID, profile_revision: int, vacancy: Vacancy, locale: Locale, job_id: UUID | None = None) -> AnalysisResult`.
- Async `SkillSuggestionService(engine, executor, policy).suggest(*, owner_id: UUID, specialization: str, locale: Locale, job_id: UUID | None = None) -> list[str]`.
- `LlmRuntime(settings, engine)` owns cached gateway/model/executor instances, provides application services, async `.aclose()`; constructor without key succeeds and provider operation fails safely before any call.

- [x] Write tests for selected immutable revision rather than current profile, owner-scoped memory, user-corrected vacancy preserved exactly, snapshot versions match actual policy, foreign/missing profile or job denied before provider, missing key zero calls, repeated runs reuse clients and isolate context, failure returns no success artifact/job mutation.
- [x] Run integration/service lifecycle tests; expect missing service failures.
- [x] Implement service reads inside short unit-of-work, release DB before executor, return immutable versioned result. Verify job type/owner where job supplied. New runtime stays reusable by ANY-649 without introducing live synchronous endpoints or automatic analysis persistence. Missing owner/profile use safe domain errors.
- [x] Run all service tests with PostgreSQL and real mocked gateway stack; verify previously deployed auth/extraction startup and routes remain functional without LLM key.
- [x] Commit `feat: expose owner-scoped analysis and suggestion services`.

### Task 6: Whole-branch verification, docs and dev rollout

**Files:** Modify `backend/README.md`, `contracts/fitcheck.openapi.json`, `lib/backend/generated/schema.ts`; create `backend/tests/llm/test_import_boundaries.py`, `backend/tests/analysis/test_live_canary.py`, `docs/deployments/2026-10-12-any-648-llm-gateway.md` after actual deployment.

- [x] Add import-boundary test restricting LiteLLM/PydanticAI/provider imports to gateway/structured modules; add opt-in live canary using anonymized fixture and explicit `FITCHECK_RUN_LLM_CANARY=1` plus key. Canary must skip when unavailable and never print payload/key. Run failing import guard against a synthetic prohibited module to prove enforcement.
- [x] Document policy, exact retry/deadline limits, ledger unknown usage semantics, configuration, migration ordering and deferred job/UI routes. Generate OpenAPI and TS from Python DTOs; verify planned endpoints remain planned. Review the dependency lock and configuration for secret/content telemetry.
- [x] Run `uv run --locked pytest -m 'integration or not integration' -q` with disposable PG; migration bootstrap/re-upgrade/drift; `uv run --locked python scripts/export_openapi.py --check`; root `node scripts/generate-backend-types.mjs --check`, `npm test`, `npm run typecheck`, `npm run lint`, website build in CI. Expected: no failed tests/checks; canary clearly reports skipped unless enabled.
- [x] Obtain independent final review of domain parity, retries/accounting, cancellation, owner boundaries, old JSON compatibility and dependency adapters; fix confirmed findings and rerun affected plus full checks. Mark plan tasks with evidence, not merely implementation status.
- [x] Commit final implementation/docs and push `dev` following existing user-authorized workflow. Apply additive migration 0002 before restarting dev API; verify migration head/readiness/unchanged auth/extraction. No reset or live LLM call merely to declare deployment complete. Record actual commit/check results and mark ANY-648 Done only after requirements and verification pass.

## Self-review

The six tasks cover all spec sections and five Review Focus conditions. Interfaces share
OperationContext/ProviderPolicy and one CallBudget across generation/audit; semantic retry
ownership stays in the executor. Snapshot version remains v1 for backward-compatible
optional additions. ANY-649 owns publication/job state, avoiding a synchronous API bypass.
Actual library versions/API details are verified before dependency installation and adapter
implementation; no unverified SDK signatures are requirements of this plan.
