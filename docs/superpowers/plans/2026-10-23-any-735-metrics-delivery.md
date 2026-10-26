# ANY-735 Metrics Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make analytics delivery failures observable and prove committed delivery.
**Architecture:** Preserve the boolean bridge and bounded queue. Add safe delivery diagnostics, dedicated collector counters to private operations monitoring, and a reproducible PostgreSQL verification procedure.
**Tech Stack:** Next.js 16.3, TypeScript/Vitest, FastAPI/SQLAlchemy/pytest, PostgreSQL.
**Spec:** `docs/superpowers/specs/2026-10-23-any-735-metrics-delivery-design.md`

## Global Constraints

- No persistent browser outbox, new analytics platform, identity linking or funnel redesign.
- No secrets, raw exception messages or user text in diagnostics.
- Business operations continue on telemetry failure.
- Target: existing Dokploy development; do not infer live state from local dotenv.

## Review Focus

- Late transport completion after timeout must not emit contradictory diagnostics.
- Diagnostic callbacks must not break delivery or business operations.
- Malformed/unauthorized collector requests must be counted without raw URLs or IDs.
- Collector-only runtime and database outages must retain configuration diagnostics.
- Missing collection history must remain unknown rather than zero activity.

### Task 1: Bridge and browser diagnostics

Files: `lib/metrics/bridge.ts`, `lib/metrics/client.ts`, their existing tests, and `app/api/metrics/handler.ts`/tests.
Interfaces: preserve boolean delivery return values; emit safe bounded JSON diagnostics using fixed names/reasons and numeric counters.
- [ ] Add failing tests for configuration failure, HTTP rejection, timeout, collector acknowledgement, safe logs and exhausted browser retries/overflow.
- [ ] Run `node node_modules/vitest/vitest.mjs run lib/metrics app/api/metrics` and observe intended failures.
- [ ] Implement reason-coded bridge diagnostics and aggregated browser loss diagnostics; keep callbacks/logging best effort.
- [ ] Repeat tests; expect PASS, then run TypeScript checks.

### Task 2: Private collector monitoring

Files: `backend/src/fitcheck_backend/operations/monitoring.py`, `api/middleware.py`, tests.
Interfaces: bounded route/status counters, configuration gauges and environment-scoped committed journal timestamps/counts through existing token-protected endpoint.
- [ ] Add failing tests for collector status separation, disabled/misconfigured states, collector-only runtime and database failure.
- [ ] Run focused pytest and observe intended failures.
- [ ] Implement monitoring without public endpoints or raw identifiers.
- [ ] Run focused unit/PostgreSQL tests, including duplicate replay and lifecycle rollback/persistence. Expect PASS.

### Task 3: Operational procedure and verification

Files: `backend/README.md`, `ops/RUNBOOK.md`, deployment evidence record.
Interfaces: existing CLI, private monitoring, journal/domain rows.
- [ ] Document configuration readiness, browser counters, collector rejection diagnosis, independent-transaction delivery/replay SQL, worker verification and coverage boundaries.
- [ ] Record actual local tests and live read-only observations; distinguish pending live deployment/DB evidence.
- [ ] Run lint, typecheck, relevant frontend/backend suites and `git diff --check`; review the final diff.

## Execution notes

User approved design and requested execution in current IDE session. Work in current dev checkout without creating an unsolicited worktree; do not push/deploy or commit unrelated files. Record progress here. Existing focused frontend baseline: 22 passed. Live website settings contain nonempty metrics URL/key/cookie secret and development environment; this is configuration evidence only.


## Progress and decisions

Tasks 1 and 2 implemented and verified. Task 3 local documentation/verification
complete; patched live acceptance pending (see deployment record).

Ruling: preserve 200 on the private exporter during database failure and signal
`fitcheck_database_up=0` — Prometheus discards 503 bodies — health alert also
checks database_up; consumers must use the gauge rather than exporter HTTP status.

Ruling: client losses are browser-local console diagnostics, never a claimed
global loss rate — outage can also prevent remote diagnostics — operators need
DevTools for the affected tab and cannot recover observations after tab closure.

Final review: independent reviewer found two important issues; both reproduced
RED→GREEN. Receipt checks reject empty/HTML/mismatched 200 responses and 204;
configuration/counters remain scrapeable during database outages. All 505 frontend
and 1002 backend tests pass (3/5 skips respectively); production build passes.
Minor deferred: pre-routing DELETE body rejections have general HTTP counters but
not the dedicated delete operation counter.
