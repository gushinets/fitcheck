# ANY-737 Identity Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans inline; user approved implementation. Keep changes uncommitted for the existing user deployment workflow.

**Goal:** Persist server-confirmed visitor/account/guest transitions and bounded attribution without mixing populations.
**Architecture:** The Next relay signs an existing visitor cookie's context with the existing bridge key. Backend hooks after successful auth/claim persist idempotent transitions; separate read projections resolve temporal windows conservatively. Session closure and maintenance preserve durable bounds.
**Tech Stack:** Next.js/TypeScript, Python/FastAPI, SQLAlchemy/PostgreSQL/Alembic.
**Spec:** docs/superpowers/specs/2026-10-23-any-737-identity-links-design.md

## Global Constraints

No new secrets, SMTP changes, paid calls, report formulas or cross-device stitching. Preserve ANY-736 evidence. Browser identity payloads never establish account/guest ownership. Failed analytics cannot fail successful auth/claim.

## Review Focus

- Mail failure after account commit must not create successful visitor-registration evidence.
- Delayed claim/demo deliveries must join once without changing jobs or rebinding visitors.
- Concurrent login requests and missing session closure evidence must produce unknown rather than a false account.
- Session pruning must preserve closure bounds; erased accounts must not expose old anonymous history to another account.
- Cookie absence/rotation, forged proofs and deleted visitors must never reconstruct old identity.

### Task 1: Attested visitor transport

**Files:** lib/metrics/identity-proof.ts (new), lib/backend/relay.ts, backend metrics/identity_proof.py (new), matching TS/Python tests.
**Interfaces:** X-FitCheck-Visitor-Proof contains base64url compact JSON plus HMAC-SHA256 with domain `fitcheck:metrics:identity:v1:`. Fields v=1, environment, visitorId, cookieIssuedAt (ms), issuedAt (ms), expiresAt (issuedAt+120000), requestId UUID, method POST, path exactly /v1/auth/register, /v1/auth/login or /v1/guest-claims. Backend returns VisitorContext(visitor_id,cookie_issued_at,received_at) or None; never throws for invalid proof. Existing signed visitor cookie must resolve isNew=false. Exact one cookie/header, bounded lengths, environment/path/time/signature checks.
- [x] Write/run RED tests for trusted signing and fake/missing/duplicate/expired cookies; stripping caller headers; Python signature/method/path/environment/expiry validation.
- [x] Implement with builtin crypto only and existing env; attach only to exact successful-op routes before forwarding. Run focused tests GREEN.

### Task 2: Persistence and successful auth/claim hooks

**Files:** storage metric_identity.py/models.py, migration0011, metrics/identity.py, api/auth.py/guests.py, storage/auth_repository.py, api/runtime.py, integration tests/test_metrics_identity.py.
**Interfaces:** MetricIdentityTransition stores environment, visitor/account/optional guest, kind registered/login/claim, source_id (session/receipt), auth_session_id, cookie issuance, request_started_at, occurred_at, expires_at, ended_at/end_basis. Unique(environment,kind,source_id), account/guest cascade, with auth evidence explicitly anonymized before account erasure; source/session IDs deliberately survive short-lived auth row retention. MetricVisitorBoundary stores latest anonymous floor per environment/visitor, without account IDs. IdentityRecorder.auth(context,issued,kind) / claim(context,account,guest,key) are best effort and revalidate server state inside transaction. revoke_sessions archives ended bounds in savepoint; live state remains authority if archival fails.
- [x] Add/run RED persistence tests: registered without demo, failed mail/credentials/claim, successful guest claim, retries and foreign IDs, erased visitors, analytics outage.
- [x] Implement additive models/migration and after-success hooks; claim uses real receipt and exact guest. Preserve first transition on replay. Serialize visitor erasure with recording; owner locks precede domain session reads; no new credentials in logs.
- [x] Maintain anonymous boundary on transitions/closure/deletion so erased accounts cannot donate prior history to a later registration. Run focused integration tests GREEN.

### Task 3: Bounded read projections and maintenance/erasure

**Files:** metrics/identity_queries.py, metrics/collector.py/lifecycle.py/retention.py, storage/ownership.py, operations/retention.py, integration tests.
**Interfaces:** identity_snapshot(session,environment,visitor_id,now) returns transitions and windows with explicit unknown reasons; account_at(snapshot,at) returns owner or unknown. Registration anonymous_from snapshot never crosses prior authenticated segment. Concurrent overlapping auth request windows for distinct accounts remain ambiguous until a non-overlapping transition. Half-open attribution intervals end at revoke/expiry/non-overlapping account switch. Reads never infer final bounds from a missing auth row. claim_demo_events joins only exact visitor+guest proof, including observations delivered later.
- [x] Add/run RED tests for logout/second-account, delayed/concurrent recording, session pruning, retention, account/visitor erasure and late replay; preserve original journal and stable analysis IDs.
- [x] Implement read projections bounded at100000 rows, session archival before prune, identity retention within shared maintenance limit and erasure hooks. Missing archival blocks session pruning in maintenance, not business auth.
- [x] Run full PostgreSQL/backend regression, schema drift and frontend suites GREEN; OpenAPI/TS drift check, typecheck/lint/build.

### Task 4: Final verification/review

- [x] Request a fresh independent review of the final working tree; fix material findings using regression tests RED→GREEN.
- [x] Record test evidence, migration0011 and development deployment limits; leave user changes ready to review/deploy.
