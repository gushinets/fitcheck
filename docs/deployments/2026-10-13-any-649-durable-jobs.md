# ANY-649: durable jobs and separate worker

Implementation is committed and pushed to `dev`, code commit
`0413ead943ef1255fd5567b684acad72330563ea`. Development rollout is complete;
worker health was verified before enabling API admission.

Verified accounts can create idempotent analysis and skill-suggestion jobs and
read their own status/result. Admission freezes profile, edited vacancy,
calibration and execution versions. PostgreSQL SKIP LOCKED, database-clock leases
and atomic fenced publication prevent duplicate results. Process loss permits one
recovery, with physical provider calls and repeat costs attributed to execution
tokens. API admission/read does not create an LLM runtime or need a provider key.

Validation:

- 550 backend tests passed, including PostgreSQL admission/claim/publication races,
  worker crash recovery, owner deletion, SDK boundaries and wheel packaging.
- One paid live-model canary skipped; no live provider generation was performed.
- 298 website tests passed; three optional live tests skipped.
- TypeScript, ESLint, production website build, OpenAPI/TS drift, migration drift
  and diff checks passed. Final worker Docker image built successfully.
- Independent whole-branch review found two Important races: heartbeat failure
  during terminal publication, and cancellation during threaded ledger admission.
  Both were reproduced RED→GREEN. Publication now waits for in-flight heartbeat
  completion and stops scheduling further heartbeats; cancelled ledger admission
  retains its committed ID and settles it without HTTP. Failure publication also
  reconciles stranded started rows atomically. Full suite passed after fixes.
- No Critical findings or deferred Minor findings.
- [CI passed for the code commit, including worker image build](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/38401592011).

## Development rollout evidence

Applied additive migration `0003` before API restart through the previous running
API container `6096386a5529`. The existing Alembic migration connection/lock runner
used a temporary copy of its packaged migration directory plus the exact reviewed
0003 source. Terminal printed `MIGRATED 0002 -> 0003`. The same adapter command
was checked on disposable PostgreSQL first. No reset or deletion occurred.

Dokploy `fitcheck-api-dev` reports Done for the code commit. External readiness at
`https://dev-fitcheck-api.dokploy.gcexp.ru/health/ready` returns 200 with database
ready and email unconfigured. New job GET rejects anonymous access with 401.

Created `fitcheck-worker-dev` in the existing development environment:

- Application ID `uGz_HiVcXoTo1Rid214vn`.
- Swarm app name `fitcheck-fitcheckworkerdev-x8lwxi`.
- Repository `NikitaPotapovIt/fitcheck`, branch `dev`, watch `backend/**`.
- Dockerfile `backend/Dockerfile.worker`, context `backend`, one replica.
- No public ports/domains; Swarm stop grace 140 seconds.
- User confirmed transferring existing dev PostgreSQL and DeepSeek credentials
  at action time. Secrets were saved only in Dokploy; equality was checked after
  reloading the masked editor, without printing values or storing them in Git.

Dokploy reports Done for the worker deployment at the exact code commit. Running
container `98529fcab01d` returned `WORKER_HEALTH True`, `SCHEMA_HEAD 0003`,
`DATABASE_CONFIGURED True` and `PROVIDER_KEY_CONFIGURED True`. These checks read
configuration and the worker's fresh local health marker; they did not invoke a
provider. Browser control was restored after restarting Firefox.

Then `FITCHECK_JOBS_ENABLED=true` was saved, checked after reloading the editor,
and API was deployed again. Dokploy reports Done at the code commit. Running API
container `aa9b6f3c9264` returned `JOBS_ENABLED True`,
`PROVIDER_KEY_CONFIGURED False` and `DATABASE_REVISION 0003`. External readiness
again returned 200, and anonymous job GET returned 401. Durable account POST/GET
is covered by isolated PostgreSQL HTTP tests with a fake provider, including
idempotency, admission limits and owner-scoped results.

Final backend verification after rollout: 550 passed, one paid canary skipped
(20.43 seconds). No real dev job or paid provider call was exercised. Website
integration is still ANY-653.

## Execution decisions

- Worked in the clean existing checkout while optional worktree preference was
  unanswered; potential cost is a later need to isolate changes.
- Reused the existing disposable PostgreSQL on port 55464 because a new compose
  server conflicted with that port; only the guarded `fitcheck_test` DB was used.
- Admission resolves versions through the server registry rather than constructor
  policy injection; supporting multiple versions will require extending registry
  composition.
- Gateway ledger I/O moved off the event loop so DB waits cannot delay heartbeat;
  this adds thread scheduling overhead to short ledger transactions.
- Whole-branch review preceded the deployment portion of Task 8; rollout evidence
  is recorded afterward and does not change reviewed runtime behavior.
- Deployment health/configuration remains a rollout check, outside the code-review
  verdict; the task must not be marked Done without that evidence.
- Paid provider compatibility remains opt-in; live account/model compatibility is
  unverified while the canary is skipped.

Rollback: disable new admission, drain/stop worker, preserve GET and additive
schema/data. Do not downgrade populated provider token columns or reset the DB.
