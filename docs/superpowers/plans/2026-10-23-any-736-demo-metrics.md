# ANY-736 Demo Metrics Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Observe guest demo attempts and displayed results with verified ownership.
**Architecture:** Reuse WebsiteApp's observer and queue. Store trusted guest proof in a cascading sidecar to visitor journal rows. Request correlation is the admission idempotency key; result views carry jobId and resultId. Existing domain jobs remain the authority for admission/completion.
**Tech Stack:** React, Next.js, Zod, FastAPI, SQLAlchemy, PostgreSQL, Alembic.
**Spec:** docs/superpowers/specs/2026-10-23-any-736-demo-metrics-design.md

## Global Constraints

No SMTP changes, paid calls, account attribution or funnel recalculation. Preserve the separate ANY-735 evidence. Leave implementation uncommitted for the user's existing review/deploy workflow.

## Review Focus

- Telemetry delivery precedes admission: request correlation must remain usable without inventing a job.
- Stale guest sessions and forged result IDs must never establish trusted ownership.
- Concurrent tabs must classify exactly one first view per visitor/result.
- Claim and deletion must preserve IDs and erase dependent evidence.
- Async completion after unmount must not record an unseen result.

### Task 1: Trusted collector context

**Files:** backend metrics registry/collector, new metrics/demo.py, storage metrics/models, additive migration 0010, API metrics, generated contracts.
**Interfaces:** properties.flow optional demo/account; properties.requestId optional UUID; result properties locale/inputMode/flow. Collector ingest(batch, guest_identity=None) verifies session inside its transaction. MetricDemoLink stores event/guest/request/job/result IDs and first_view. Original journal subject remains visitor.
- [x] Add failing PostgreSQL tests for owned/foreign IDs, replay, concurrent first view, invalid session, claim/deletion.
- [x] Run tests and confirm RED.
- [x] Implement strict contracts and sidecar. Lock guest owner before session verification, preserve claim receipt ownership and original IDs. Persist request key even before admission; jobs may later be joined by guest origin/key. Never infer admission from an attempt.
- [x] Run focused integration tests; regenerate OpenAPI/TS contracts.

### Task 2: Relay and demo observations

**Files:** lib/metrics/types.ts, bridge.ts, app/api/metrics/handler.ts, lib/web/server.ts, components/web/demo-analysis.tsx, website-app.tsx and tests.
**Interfaces:** sendMetrics accepts optional allowlisted guest cookie; server analyzeGuest(input, onRequest?) reports stable request UUID before admission; completed result includes jobId. Demo receives existing observe callback.
- [x] Add failing relay/transport/component tests: RU/EN input, URL, requests, resume, error/quota, rerender and reopen.
- [x] Run tests and confirm RED.
- [x] Forward only the one current guest cookie; implement isolated callback errors; observe result only in committed effect, suppress duplicate renders and unmounted async work.
- [x] Run frontend tests and typecheck.

### Task 3: Verification and review

**Files:** task evidence and this plan.
- [x] Run backend unit/integration regression suites, frontend suite, lint/typecheck, generated contract checks and build.
- [x] Request fresh final code review; fix material findings with regression tests.
- [x] Record exact results and remaining live deployment limitations. Leave changes ready for user deployment.
