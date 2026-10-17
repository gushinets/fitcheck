# ANY-651 local validation and rollout

Implementation branch: `feat/any-651-guest-quotas`, isolated worktree
`.worktrees/any-651`, base `4fa589327d0e123beecde03e23e3c4aa4f3e610b`.
This record describes local validation. No push, shared dev deployment, production
migration or admission toggle has been performed. Website UI remains ANY-579/653.

## Local evidence

- Complete backend suite runs with production settings/provider keys removed,
  dotenv disabled, and worktree source explicitly selected. PostgreSQL 17 uses
  project `fitcheck-any651`, disposable `fitcheck_test`, localhost port 55464.
- Full backend suite: 795 passed, 1 skipped (paid provider canary).
- Frontend: 400 passed, 3 skipped; TypeScript, ESLint, OpenAPI and generated
  TypeScript drift checks passed. Production webpack build passed after allowing
  its existing Google Fonts download.
- API and worker images built from their separate Dockerfiles.
- A second empty `fitcheck_any651_smoke_test` database was migrated from scratch
  to 0008 using the API image. Alembic check reported no new upgrade operations.
- Both local image healthchecks passed. Actual HTTP readiness, guest bootstrap,
  quota remaining=1 and account-cookie isolation passed. Provider-call count=0.
  The worker used a nonfunctional placeholder key and an empty queue, never a
  real provider credential. Disposable API/worker containers are task-owned.
- A fresh whole-branch review found three Important issues, all reproduced
  RED and fixed in one pass: financial settlement after recovery, admission
  time after blocking locks, and synchronous proof I/O on the ASGI loop.
  All 795 backend tests pass after those fixes. No Critical findings remain.
  One Minor remains deferred: malformed non-ASCII guest CSRF headers may return
  500 instead of 403; authorization is still denied. Normal browser-generated
  tokens are ASCII. Add token-pattern validation in a follow-up.

## Deployment remains pending

1. Review/integrate the exact branch commit and obtain green CI; record the final
   commit and CI URL with the actual rollout. Build API and worker from that SHA.
2. Pause admission on the old image. Drain or inspect existing frozen jobs; do
   not delete them. Keep database backups and the old images available.
3. Apply additive 0008 once, then deploy matching API and worker. Their exact-head
   checks mean an old 0007 image cannot run against 0008. Coordinate both services;
   switching only one image is not a rollback strategy.
4. Verify schema, API readiness and worker heartbeat. Test guest bootstrap/quota,
   cookie/CSRF isolation and same-key admission with a nonpaid test boundary.
5. Enable account jobs and `FITCHECK_GUEST_ENABLED` only after these checks. Use
   the documented default quotas and server spending ceilings unless deliberately
   reconfigured. Observe provider unknown usage/exposure separately from actual
   estimated spend.
6. Save API/worker deployment IDs, the exact SHA, CI URL and health evidence.
   Local build/health evidence above does not prove a shared deployment.

The earlier GitHub→Dokploy webhook TLS-chain failure is unresolved by this work.
Use an authorized manual deployment or administrator certificate repair; never
turn off TLS verification. No shared certificate or real `.env` was changed.

For rollback, disable admission, preserve all frozen job/accounting data and
coordinate compatible API/worker images with the database head. Do not downgrade
0008 merely to boot an old image: its down migration removes guest/session and
budget records. Product failures release product credit, while crash/unknown
physical-call exposure remains conservative across recovery and erasure.

## Review evidence and execution decisions

The final reviewer independently read the whole branch (base4fa5893 through
ea47468). No production deployment or paid request was part of that review.
Regressions prove that recovery cannot refund conservative exposure, expired
sessions/leases cannot pass admission after owner/window waits, UTC midnight
restarts the financial transaction on the new windows, and a delayed guest proof
does not block health requests. The strengthened legacy test creates a v1 job on
0007, migrates to0008, executes generation/audit through the frozen executor and
real ledger with a fake provider, publishes the original snapshot and acquires no
retroactive product reservation.

Execution decisions, with their tradeoffs:

- use existing locked Python virtualenv executable with this worktree's pytest pythonpath rather than duplicate dependency installation — same lockfile/environment, isolated source/tests — cost if wrong: packaging test detects editable-path confusion.
- implementation and tests stay in the isolated worktree; no shared dev push/deploy authorized by choosing native execution — preserves user's current dev branch — cost if wrong: handoff needs integration later.
- explicitly set child-process PYTHONPATH to the worktree source when reusing root virtualenv — export subprocess otherwise loaded the old editable checkout — cost if wrong: false cross-checkout validation, covered by export/package tests.
- OpenAPI tests derive implemented paths from registered runtime routes during staged task rollout — ANY-651 has both implemented and planned routes until Task6 — cost if wrong: final contract suite still requires all three routes.
- guest quota window anchors persisted guest.created_at/expires_at, not later configured TTL — changing settings cannot create a fresh bucket — cost if wrong: existing guests retain initial policy until expiry as intended.
- use serialized UTF-8 byte ceiling plus explicit framing allowance for the pinned text-only model rather than adding a guessed tokenizer mapping — one byte per token is conservative across Unicode and unknown model tokenization — cost if wrong: conservative admission may reject long prompts earlier than necessary; unsupported modalities/context fail closed.
- durable budget transaction lives in BudgetRepository called by ProviderLedger, with a thin service export — keeps the existing physical-send boundary authoritative and avoids nested transactions — cost if wrong: service API can be expanded without changing financial semantics.
- v2 suggestions also freeze mode/session and physical limits, while v1 decoding remains — suggestions need the same durable retry/expiry protection — cost if wrong: future suggestion workers must support v2 alongside analysis.
- v2 normalized analysis exposes a compatibility request property internally while storing profileRevision/vacancy/locale separately — avoids persisting a fabricated guest request revision and keeps existing executor/publication semantics — cost if wrong: accessor can be removed when downstream code normalizes directly.
- ProviderLedger accepts an optional clock for deterministic expiry tests; production keeps database clock_timestamp — fixed January auth fixtures otherwise make an October database clock reject all guest calls before the specific session expiry being tested — cost if wrong: incorrect injected clocks affect tests/in-process callers only.
- anonymous deployment reservation links remain after account erasure alongside anonymized provider rows; owner/job windows and all personal links cascade — preserves conservative spend and existing anonymized usage accounting — cost if wrong: anonymous technical records remain until operational retention cleanup.
- UTC-window assertions live in PostgreSQL quota reservation tests rather than a duplicate pure windows file — they prove real settlement on original buckets — cost if wrong: isolated calendar-only tests are less granular, but UTC-midnight behavior remains covered.
- website demo UI and existing Next.js provider routes remain ANY-579/653 — approved scope is the Python backend boundary — cost if wrong: website continues existing behavior until separate UI integration.
- shared rollout/TLS/live-provider validation stays pending — no shared deployment or paid canary authorized; local zero-send smoke is the evidence — cost if wrong: environment-specific deployment problems remain unverified.
- session/IP limits do not promise one demo per person after cookie deletion — approved opaque-session policy deliberately permits bounded new sessions — cost if wrong: one person can use multiple demos within IP issuance limits.
- scheduled retention cleanup stays deferred — FK erasure and anonymous spend retention are implemented; periodic expired-record cleanup is outside scope — cost if wrong: expired technical/guest rows persist until maintenance is added.

Final code images (after review fixes) were rebuilt and rechecked locally:
API manifest `d04b813a24fc577699cb94bc9deee1f074886100120f536d08a93f08995a795b`,
worker manifest `9b23fb8f463a38bf56b2a92f0f21e977d36cb11a0b85b0fe728d51c60e0c0079`.
Both healthchecks passed again; schema drift, actual HTTP bootstrap/quota and
account isolation passed, with zero provider-call rows in the smoke database.
The disposable task-owned containers were stopped after validation. Linear stays
in review until the branch is integrated; shared dev deployment is still pending.
