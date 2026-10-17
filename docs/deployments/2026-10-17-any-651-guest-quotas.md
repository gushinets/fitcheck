# ANY-651 local validation and rollout

Implementation branch: `feat/any-651-guest-quotas`, isolated worktree
`.worktrees/any-651`, base `4fa589327d0e123beecde03e23e3c4aa4f3e610b`.
This record describes local validation. No push, shared dev deployment, production
migration or admission toggle has been performed. Website UI remains ANY-579/653.

## Local evidence

- Complete backend suite runs with production settings/provider keys removed,
  dotenv disabled, and worktree source explicitly selected. PostgreSQL 17 uses
  project `fitcheck-any651`, disposable `fitcheck_test`, localhost port 55464.
- Full backend suite: 784 passed, 1 skipped (paid provider canary).
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
- A fresh whole-branch review is the final gate before integration. Its results
  and any verified fixes are recorded in subsequent commits on this branch.

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
