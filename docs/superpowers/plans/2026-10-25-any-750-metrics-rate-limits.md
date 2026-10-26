# ANY-750: reliable bounded metrics delivery

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent one visitor from consuming the normal metrics budget and retain batches across temporary 429 responses.

**Architecture:** Keep the existing relay, PostgreSQL collector and memory-only client. Relay defaults: 600 accepted requests/minute/process, 30/visitor/process. Collector defaults: 1200 requests/minute/environment, 60/visitor/environment, shared through PostgreSQL. Support two relay processes at their full default capacity. Rejected per-visitor requests do not consume aggregate capacity. No raw IP storage; relay keys come from verified cookies, backend keys from authenticated, validated visitor subjects.

**Tech Stack:** Next.js 16.3 route handlers, TypeScript, FastAPI, SQLAlchemy/PostgreSQL, Vitest/pytest.

**Spec:** Linear ANY-750 (read 2026-10-25); acceptance criteria remain authoritative.

## Global Constraints

- Existing origin, cookie, payload, receipt and deletion protections remain intact.
- Queue remains 100 events including in-flight events; batches remain 20 events/32768 bytes.
- Three attempts per batch; 120 seconds maximum retry lifetime. Honor valid Retry-After seconds or HTTP dates; missing/invalid values wait 60 seconds. Never shorten a valid delay to retry early.
- Normal capacity control: 31 visitors, each two pulses plus two page/action requests per minute (124 HTTP requests). Also test two independent relay instances against one collector scope.
- User authorized implementation with “делай”; execute in place on dev, preserving the existing unrelated deployment-document edit. No deployment, Linear messages, merge or push included.

## Review Focus

- Burst rejection must not exhaust the aggregate budget for other visitors.
- Backend 429 must retain delay through bridge and relay; only confirmed receipts count as delivery.
- Flush, tracking and visibility changes must not bypass a pending retry delay.
- Dispose/identity deletion must cancel retry timers without sending old events.
- Oversized delays, queue overflow and retry exhaustion must remain bounded and observable.

### Task 1: Delay-aware transport and client

Files: `lib/metrics/{delivery,client,bridge}.ts`, associated tests, `app/api/metrics/handler.ts`.

- [x] Write and run failing tests for delay propagation, wait/restore with original IDs, invalid/date headers, exhaustion, overflow and cancellation.
- [x] Add `DeliveryResult` and Retry-After parsing, preserving boolean bridge callers; expose a detailed event-delivery entry point to the relay.
- [x] Retain batches during cancellable bounded waits; preserve existing timeout and identity-generation protections.
- [x] Run transport/client/relay tests and TypeScript checks.

### Task 2: Fair capacity across relay and backend

Files: relay handler/route/tests, backend metrics limits/API/collector/settings and database tests, example configuration.

- [x] Write and run failing fairness, normal-load, aggregate exhaustion, window-reset and shared-instance tests.
- [x] Implement bounded relay counters and persisted collector aggregate/per-visitor counters with Retry-After on 429. Validate configuration limits.
- [x] Prove original event IDs deduplicate after a rate-limited retry through real PostgreSQL ingestion.
- [x] Run focused PostgreSQL tests and frontend tests.

### Task 3: Verification and operator handoff

- [x] Document budgets, supported replicas, normal traffic, retry lifetime, diagnostics and memory-only loss boundaries.
- [x] Run frontend suite, typecheck/lint and backend suite; report any existing failures separately.
- [x] Review diff against ANY-750 acceptance criteria and preserve unrelated work.

## Execution record

- Initial inspection: both current budgets are 60/minute; bridge returns boolean and drops Retry-After; browser retries immediately. Existing client/relay regression tests located. Next route-handler guide read locally before edits.

- Task 1 complete: client and relay failures observed before implementation; transport carries safe Retry-After metadata, retries preserve IDs and cancellation. Added cross-batch cooldown and browser-suspension regressions after reproducing their failures.
- Task 2 complete: PostgreSQL fairness/normal-load/shared-worker tests observed failing, then passing. Expanded metrics integration: 81 passed. Test-only SimpleNamespace replaced with real Settings after new fields exposed the incomplete fixture.
- Task 3 complete: frontend 546 passed / 3 skipped; backend default suite 688 passed / 2 skipped / 409 integration deselected; metrics PostgreSQL suite 81 passed. TypeScript, full ESLint and diff whitespace checks passed. Backend suite has one pre-existing SDK/Pydantic ReadOnly warning. Initial wheel packaging check was blocked by sandbox PyPI access and passed after network-enabled rerun. Direct local Node entry points used because pnpm launcher could not resolve/verify its requested registry version in the restricted environment.
- Review: independent read-only reviewer found one Important issue (late browser timer could exceed batch lifetime); reproduced, corrected and re-reviewed with no remaining Important/Critical findings.
- Full frontend run exposed an existing asynchronous effect assertion race in test_ordered_local_registration_profile_analysis_view_events; it passed alone. Assertion now uses waitFor for the emitted view instead of assuming DOM appearance means effects have run; full suite passed afterward.
- Delivery: changes remain uncommitted in the current workspace; no deployment, push or external issue writes performed. Existing unrelated deployment-document changes preserved.
