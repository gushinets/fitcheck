# ANY-737 — trusted identity links

Implementation is prepared locally on top of ANY-736 (`95ae223`). No commit,
push, deployment or live database migration was performed for ANY-737.

## Changes

The website relay signs an existing verified visitor cookie for successful
registration, login and guest-claim routes using the existing metrics bridge
key. Browser-supplied identity/proof headers cannot establish account ownership.
The API rechecks account/session/guest/receipt state and stores idempotent
transitions after successful business operations. Missing or invalid metrics
context and analytics failures preserve the business response and leave coverage
unknown. Mail failure does not create a successful visitor-registration link.

Separate read projections preserve original event populations/times and guest
job/result IDs. Logout, expiry, account switches and overlapping requests have
explicit temporal bounds. Claim joins require matching visitor/guest provenance,
including observations delivered after claim. Session archival precedes pruning;
failed archival retains the source session.

Account deletion removes domain identifiers and claim links. Auth evidence
becomes anonymous temporal guards with no account, guest, operation or session
identifiers. Guards prevent another account from inheriting erased history;
coverage remains unknown until a later non-overlapping login or the original
hard expiry. Guards are excluded from confirmed transition results. Visitor
erasure deletes links, guards and boundaries and retains its existing opaque
tombstone. Closure/deletion only update existing boundaries, so stale operations
cannot reconstruct a concurrently erased visitor association. Retention includes
these tables in the existing bounded 180-day maintenance budget.

No new environment variables or public API contracts. No SMTP bypass or paid
provider calls. Report formulas/dashboard changes remain ANY-738.

## Review and verification

Independent read-only review found two material erasure issues: deleting a
switch target reopened an older account's interval, and a concurrent account
and visitor deletion could recreate the visitor boundary. Both were reproduced
with failing PostgreSQL tests before fixes. Regressions cover ordinary and
overlapping switches and an interleaved visitor deletion on another connection.
The same boundary recreation pattern was separately reproduced and fixed in
session rearchival. Missing-session uncertainty is capped at recorded expiry.

Final backend: **1040 passed, 5 skipped**, one preexisting SDK/Pydantic warning.
Frontend: 521 passed, 3 skipped. TypeScript, full ESLint and production webpack
build passed. OpenAPI and generated TypeScript drift checks passed. PostgreSQL
migration downgrade/reupgrade and schema drift checks passed after the erasure
fixes. One existing demo component test now waits for effect-installed observer
state instead of relying on the earlier rendered text as a timing signal.

## Dokploy rollout

Deploy the backend image containing migration **0011**. Run these commands in
the development API container terminal (`api-dev`), using that container's
configured development database, before starting/restarting the matching API
and worker:

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade
/app/.venv/bin/python -m fitcheck_backend.storage.migrate check
```

Expected drift check: `No new upgrade operations detected.` Migrations are an
explicit deployment step; application startup does not run them. A failed check
must be resolved before treating rollout as complete. Then deploy the matching
website relay. Existing website METRICS_BRIDGE_KEY must match backend
FITCHECK_METRICS_INGEST_KEY and the metrics environment must agree.

Development smoke is pending deployment. SMTP is still unconfigured by the
user's choice, so no live successful-registration/verified-claim acceptance is
claimed. Automated tests use a capturing mailer and seeded guest result fixtures.
The separate ANY-736 deployment evidence is preserved.
