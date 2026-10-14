# FitCheck OpenAI Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch current website and durable worker to the user-selected `gpt-6-luna`, configure supplied credentials locally/in Dokploy and preserve output contracts and physical-call accounting.

**Architecture:** Keep the existing OpenAI TypeScript SDK and Python LiteLLM boundary, targeting OpenAI Chat Completions with explicit reasoning disabled. Model selection is a shared server registry used for admission and execution, with immutable historical envelopes and provider ledger. The preceding metrics plan supplies the website attempt sink and reports.

**Tech Stack:** Existing OpenAI SDK, LiteLLM/Pydantic AI/SQLAlchemy, Vitest/pytest and Docker/Dokploy.

**Spec:** `docs/superpowers/specs/2026-10-14-fitcheck-metrics-openai-design.md`.

## Global Constraints

- Depends on completed `docs/superpowers/plans/2026-10-14-fitcheck-metrics.md`; run sequentially.
- User explicitly chose `gpt-6-luna`, not `gpt-6.1-sol` or a fabricated `gpt-6.1-luna`.
- Website/worker env names: `OPEN_AI_KEY`, `OPEN_AI_MODEL=gpt-6-luna`; Python uses explicit aliases. API admission needs the model, not the provider key.
- Endpoint HTTPS `api.openai.com`, port 443, `/v1/chat/completions`, no query/userinfo/redirects. LiteLLM model `openai/gpt-6-luna`, `reasoning_effort=none`, JSON object, `max_completion_tokens`, no temperature or DeepSeek thinking extension.
- Preserve existing analysis 120s/45s attempt deadlines, 8-call maximum; suggestions 60s deadline/4-call maximum; transport/semantic limits 2 each. SDK hidden retries remain disabled.
- Keep old inputs, versions and ledger immutable. Drain old-model jobs before activating the new registry; never reinterpret old jobs under OpenAI.
- Provider key remains local or in server secret stores, never browser public env, tracked code, output/logs or raw exception text. Preserve the supplied key without echoing it.
- No paid canary without a concrete spend-cap approval. Verify official docs and installed SDKs; model catalog membership alone is not account-access proof.

## Review Focus

1. Unknown model or old frozen envelope cannot silently call another provider/model (Task 1).
2. SDK retries, redirects or stripped reasoning/output params cannot bypass physical-call budgets (Tasks 1, 2).
3. Cancelled admission or heartbeat loss cannot leak a started ledger call or publish stale work (Task 1).
4. Cache/reasoning tokens, missing usage and failed audit/retry costs cannot fabricate zero expense (Task 3).
5. Partial fleet deployment cannot admit OpenAI jobs to an incompatible DeepSeek worker (Task 4).

## File Structure

Python config/policy/runtime/envelopes define the resolved model registry;
`backend/src/fitcheck_backend/llm/litellm_adapter.py` alone owns provider HTTP. TypeScript `lib/analysis/openai.ts`
and `lib/skill-suggestions/openai.ts` replace active DeepSeek transports while
reusing service prompts/validation and Task 5 metrics sink. Versioned pricing is
isolated from product outputs. Deployment documents verify all three services.

### Task 1: Shared OpenAI configuration and worker boundary

**Files:** Modify `backend/src/fitcheck_backend/config.py`, `backend/src/fitcheck_backend/llm/policy.py`, `backend/src/fitcheck_backend/llm/runtime.py`, `backend/src/fitcheck_backend/llm/litellm_adapter.py`, `backend/src/fitcheck_backend/jobs/envelope.py`, `backend/src/fitcheck_backend/jobs/execution.py`, `backend/src/fitcheck_backend/jobs/admission.py`, `backend/src/fitcheck_backend/api/runtime.py`, `backend/src/fitcheck_backend/worker/runtime.py`, `backend/.env.example`; test `backend/tests/llm/test_openai_adapter.py`, `backend/tests/jobs/test_envelope.py`, `backend/tests/integration/test_job_execution.py` and existing gateway/worker tests.

**Interfaces:** `Settings.open_ai_key: SecretStr | None` aliases `OPEN_AI_KEY`; `.open_ai_model` aliases `OPEN_AI_MODEL`, defaults `gpt-6-luna`, exact allowlist. `analysis_policy(model: str='gpt-6-luna')` and `suggestion_policy(model: str='gpt-6-luna')` return OpenAI ProviderPolicy with new policy version `fitcheck.llm.policy.v2`; preserve other spec budgets. `execution_versions(job_type: str, *, model: str='gpt-6-luna')` and `validate_supported_versions(envelope, *, model: str='gpt-6-luna')` resolve the same configured registry in admission and worker. Adapter exposes existing complete/available/aclose signatures and ProviderReply fields.

- [ ] Recheck official model endpoint/parameters and installed LiteLLM/OpenAI support without generating a paid response. Write `test_openai_aliases_and_invalid_model_fail_safe`, `test_api_admits_openai_versions_without_provider_key`, `test_adapter_outbound_exact_host_path_reasoning_none_and_max_completion_tokens`, `test_redirect_and_second_send_blocked`, `test_old_deepseek_envelope_rejected_before_http`, `test_concurrent_calls_have_independent_send_counters`. Existing cancellation/lease tests must remain applicable and pass with OpenAI fixtures.
- [ ] Run targeted config/envelope/SDK-boundary tests; observe old provider/parameters fail assertions. Use mock transport with complete provider-shaped responses to exercise installed SDK, not mocked `acompletion` only.
- [ ] Implement aliases and fail-safe model resolution; update composition so Settings model is injected consistently rather than client input. Route LiteLLM explicitly through OpenAI with one-send guarded client, no catalog download/telemetry, no dropped parameters and safe errors. Set max_completion_tokens to existing 1200 analysis/1000 audit/500 suggestions caps. Preserve gateway cancellation settlement and fenced publication. Retain historical DeepSeek fixtures/records only where verifying old-version rejection or accounting history.
- [ ] Run all backend `tests/llm`, `tests/jobs`, `tests/worker` and relevant PG execution/publication/HTTP/recovery suites with `-m 'integration or not integration'`; expect pass, zero real HTTP and correct new frozen provider metadata.
- [ ] Commit `feat: execute frozen worker jobs through OpenAI Luna`.

### Task 2: Current website OpenAI transports and local configuration

**Files:** Create `lib/analysis/openai.ts`, `lib/analysis/openai.test.ts`, `lib/skill-suggestions/openai.ts`, corresponding test; modify `app/api/analyze/route.ts`, `app/api/skill-suggestions/route.ts`, associated route tests, existing opt-in live-test active transport imports and `.env.example`; retire obsolete active DeepSeek transport modules only after all imports are migrated. Update user `.env.local` without staging it.

**Interfaces:** `createOpenAITransport({apiKey, model='gpt-6-luna', operation, attemptSink}): AnalysisTransport` retains `.verifyGrounding`. `createOpenAISkillSuggestionTransport` returns existing SkillSuggestionTransport, consumes same Task 5 sink. Server routes read OPEN_AI_KEY/MODEL and return existing safe `server_not_configured` errors. Pure schema/prompt/grounding/service modules retain their public types.

- [ ] Read installed Next route-handler/environment docs. Write `test_route_reads_open_ai_env_not_deepseek`, `test_luna_transport_json_output_and_grounding_preserved`, `test_no_deepseek_params_or_hidden_retry`, `test_429_timeout_invalid_json_safe_errors`, `test_provider_sink_records_generation_audit_and_retry`, `test_provider_error_logs_no_raw_message_or_key`.
- [ ] Run new transport and existing route tests; observe missing OpenAI factory/wrong environment assertions.
- [ ] Implement supported OpenAI params/endpoint and safe error mapping with Task 5 sink. Preserve prompt factual grounding, language handling, retry/deadline and schema behavior. Remove obsolete active imports/env variables; never rewrite historical deployment records. Set OPEN_AI_MODEL in .env.local through secret-safe file editing, preserve OPEN_AI_KEY, document server-only names in root/backend templates. Existing METRICS_* and origin values remain intact.
- [ ] Run `pnpm exec vitest run lib/analysis lib/skill-suggestions app/api/analyze app/api/skill-suggestions`, `pnpm typecheck`, env-name validation without printing values and `git check-ignore .env.local`; expect pass and no key in diff.
- [ ] Commit tracked changes `feat: switch website analysis and suggestions to OpenAI Luna`.

### Task 3: Versioned OpenAI usage and cost estimates

**Files:** Create `backend/src/fitcheck_backend/llm/pricing.py`, `lib/metrics/pricing.ts`, associated tests; modify backend reply/accounting DTO/models and additive `backend/migrations/versions/0005_provider_usage_basis.py` if extra usage fields are needed, provider adapter/repository and normalized metrics queries; update package/head checks and README.

**Interfaces:** `estimate_openai_cost(usage: ProviderUsage, *, model, rate_version, service_tier, processing_region) -> CostEstimate(amount: Decimal | None, currency, basis, rate_version, reason)`; TypeScript equivalent uses decimal-safe integer/rational arithmetic and matches fixture outputs. Versioned snapshot contains provider/model/date, input/cache/write/output rates and applicable premiums. Worker and website normalized attempts expose optional cached-input/cache-write/reasoning counts, cost basis/rate version; total completion tokens already containing reasoning must not be charged twice.

- [ ] Verify official pricing for selected model immediately before pinning rates; record exact source/date. Write `test_cached_input_not_charged_as_uncached`, `test_reasoning_output_not_double_counted`, `test_unknown_cache_or_tier_returns_unknown_not_zero`, `test_failed_generation_and_audit_cost_in_successful_operation`, `test_historical_deepseek_cost_stays_estimated`, `test_ts_python_price_fixture_parity`, `test_migration_preserves_existing_provider_usage`.
- [ ] Run new pricing/report/migration tests, observe missing basis/cache behavior. No real provider response needed; use documented usage-shaped fixtures.
- [ ] Implement versioned estimates for standard/global text usage; any unsupported usage/tier/region/large-context condition returns unknown with reason rather than a guessed price. Validate all nonnegative integer fields and cache subdivisions <= total input. Preserve historical ledger values and annotate provenance without pretending invoice verification. Normalize both website and backend costs into the preceding report without row fanout.
- [ ] Run pricing, provider accounting and full metrics report suites, migration/head drift and TS typecheck; expect exact estimates, unknown coverage and preserved history.
- [ ] Commit `feat: report versioned OpenAI token cost estimates`.

### Task 4: Review and matched provider rollout

**Files:** Modify root/backend README and env templates as required; create `docs/deployments/2026-10-14-fitcheck-openai.md`.

**Interfaces:** Existing Dokploy website, API, worker. Only website and worker receive supplied OPEN_AI_KEY; all registry consumers receive matching OPEN_AI_MODEL. CLI metrics report proves provider/model attribution. API admission feature flag controls fleet transition; no public provider key or dashboard.

- [ ] Run full backend PG suite, migrations/package/OpenAPI/TS checks, all frontend tests/typecheck/lint/production build, both backend image builds and `git diff --check`. Preserve optional paid-test skips. Request fresh whole-branch review under selected execution skill and fix verified Important/Critical findings RED→GREEN in one pass.
- [ ] Commit, push dev and verify CI exact runtime commit. Disable new job admission; inspect nonterminal jobs grouped by frozen provider/model. Drain using existing worker; if not drained, keep previous provider/worker/key available and stop fleet switch. Never delete/reinterpret queued work. Apply additive 0005 through approved migration runner if Task 3 introduced it.
- [ ] Prepare concrete secret configuration, then transfer supplied local OpenAI key to the existing website and worker using supported secret storage. Respect any Computer Use action-time grant requirement and ask only at this ready-to-apply step. Do not regenerate the supplied credential or show its value. Deploy API's new registry with admission still off, then worker; verify matching model, schema and health without paid generation. Re-enable admission after worker compatibility is confirmed, then deploy website.
- [ ] Verify external readiness, anonymous jobs rejection, server model/env booleans and telemetry/report provider attribution using mock/disposable test evidence. If live compatibility canary is needed, ask for a defined cap before calling OpenAI; record skipped/live status accurately. Remove obsolete active DeepSeek key variables only after successful OpenAI startup/config verification; preserve historical costs.
- [ ] Save deployment/CI/migration/model-health evidence and limitations, commit/push clean tracked work, preserve .env.local outside Git and collect all execution rulings/deferred review findings. Only then return to the next backlog task.

## Plan self-review

Spec OpenAI config/immutable envelopes/guard/accounting map to Task 1;
website/local env migration to Task 2; cost provenance/coverage to Task 3;
matched fleet drain/deploy/rollback and proof to Task 4. All five Review Focus
cases have named tests or explicit deployment gates. Task 2 consumes the metrics
plan's ProviderAttemptSink/OperationContext; Task 3 extends its normalized costs
without replacing existing events. The registry's exact model parameter is
consistent in both admission and worker. No ANY-653 product migration is hidden
in this plan. The user-supplied secret is never staged and the default model is
the explicitly selected Luna.
