# ANY-748 — bounded browser clocks in account result proof

Date: 2026-10-25 (Europe/Moscow). Implementation for
[ANY-748](https://linear.app/paveldik/issue/ANY-748). The development rollout authorized
after implementation is recorded below.

## Problem and time policy

The collector accepted browser timestamps within five minutes of receipt, but the
report compared those timestamps directly with server result creation/completion
and confirmed identity intervals. A real immediate view with a browser clock 60
seconds behind therefore lost account activation; a clock 60 seconds ahead changed
TTV. A larger skew was replaced by receive time and could incorrectly look trusted.

Formula version is now `server_v3`. This change applies to confirmed account
`analysis_result_viewed` and `feedback_saved` observations. Other browser actions,
demo observations and backend domain timestamps retain their existing time rules.
No clock synchronization endpoint or client-side offset estimate is introduced.

For a result observation with raw browser timestamp C, collector receipt R, and
server readiness D = max(analysis.created_at, job.finished_at):

1. Keep C as `metric_journal.submitted_occurred_at`. Journal `occurred_at`, receipt,
   submitted payload hash and the existing `clock_adjusted` flag retain their roles.
2. Require a successful linked result/job, valid operation correlation and account
   ownership. Require `abs(C-R) <= 300 seconds`, inclusive. This is a bounded
   client-time admission policy, not proof that network delay is zero.
3. Require D <= R. The possible observation interval is [max(C-300 seconds,D),R].
   Domain readiness bounds when an existing observation could have happened; it
   never creates an observation or substitutes job completion for a view.
4. Require one confirmed account continuously covering the entire **closed** interval.
   An overlapping other owner, erased/missing session evidence, logout gap or end
   exactly at receipt is unknown. Even a same-owner logout/login gap is rejected.
   The result owner must match the single confirmed account; delivery-time login
   alone cannot donate an earlier event to a new account.
5. Use R for the confirmed view and feedback in account report math. It is explicitly
   a **server receipt upper bound**, including delivery delay, not an exact claim of
   human observation time. TTV, activation, acquisition activations and first-view
   retention use the same projection. Calendar cohorts use the receipt date, so a
   delayed delivery near midnight can move a cohort to the following day.

The existing metrics client still creates the observation itself when the result is
visible (ANY-747). No event means no product activation. Event IDs/payload hashes
continue to deduplicate replay, independently of a later receipt or correction.

Reports expose `observation_time_scope`, `observation_time_basis`,
`client_clock_tolerance_seconds`, `identity_time_policy`, `ttv_interpretation`,
`clock_corrected_views` and `unknown_account_views`. Out-of-bound clocks are
`clock_out_of_bounds`; legacy adjusted rows without a recoverable raw timestamp are
`missing_original_clock`. They cannot acquire identity by using their replaced time.
The existing limited-coverage/lower-bound interpretation remains applicable.

Receipt-range loading includes result observations whose raw clock is beyond the
report cutoff, but does not use observations received at or after that cutoff.
Private result/identity proof and domain/account/visitor erasure rules remain intact.
The new column contains only a timestamp and follows journal deletion/retention.

## Migration and compatibility

Revision **0015**, from 0014, adds nullable UTC `submitted_occurred_at`.
It backfills old, unadjusted website-client rows from their stored occurrence time.
Adjusted historical raw timestamps cannot be recovered from a hash and stay NULL.
Old writers can still insert rows after migration; new report code requires 0015.
The migration does not rewrite event payload hashes, identities or stored occurrence
times. Downgrade removes the raw-time column and loses that provenance; use normal
application rollback rather than downgrading a live analytics ledger.

The following commands must run from the **new image containing revision0015**,
with the same dev database configuration as the API:

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade
/app/.venv/bin/python -m fitcheck_backend.storage.migrate check
```

Prefer a separate migration job before replacing API/worker images. Readiness checks
compare the exact schema head, so plan the migration and API image handoff together.
Do not depend on opening a shell in a new API container that is already failing its
healthcheck because migration has not run.

If Dokploy has no separate job available, the previously verified recovery pattern
can apply migration before starting the new API. Temporary Run Command `/bin/sh`,
with two arguments:

```text
-ec
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade && /app/.venv/bin/python -m fitcheck_backend.storage.migrate check && exec /app/.venv/bin/python -m fitcheck_backend
```

Deploy, verify DB revision0015 and public `/health/ready` 200, then clear the temporary
command and both arguments, Save and deploy again to apply the normal Dockerfile CMD.
Confirm the final container is running/healthy and readiness remains200. This task
has not changed Dokploy settings or deployed the new image. No new env variables or
frontend build changes are required for ANY-748.

## Verification

- Real collector → PostgreSQL → SQL/report controls reproduce the original defect:
  12 of the initial14 cases failed before implementation, including −60 activation,
  +60 TTV, excessive skew and delayed boundary cases.
- Twenty new integration controls cover normal, ±60, inclusive ±300, ±301 and ±3600;
  raw clock preservation and duplicate event IDs; consistent account activation/TTV
  and day7 retention with explicitly complete source coverage; delayed delivery after
  logout/switch/same-owner gap, overlapping sessions and foreign results; exclusive
  logout boundaries, pre-result receipt and report cutoff without future lookahead.
- A real0014→0015 migration roundtrip verifies known raw timestamps, irrecoverable
  adjusted history, stable event hashes and schema drift checks.
- Backend default suite: **691 passed, 2 skipped**, including an installed wheel
  with schema head0015. The first sandbox run could not fetch hatchling from PyPI;
  the successful run used approved network access.
- Independent review found no substantive issues. Its coverage-label suggestion
  was addressed by explicitly scoping the time policy to result views/feedback.
- Full integration suite: **443 passed, 3 skipped**. Two historical migration
  fixtures were adapted to insert only historical columns instead of using the
  current ORM model against pre0015 schemas.

Local commands (only disposable `fitcheck_test` PostgreSQL, synthetic data):

```sh
backend/.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests -q
FITCHECK_TEST_DATABASE_URL='postgresql+psycopg://fitcheck_test:fitcheck_test@127.0.0.1:55464/fitcheck_test' backend/.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests -m integration -q
```

No paid LLM calls or live dev database changes were performed.


## Authorized development rollout — 2026-10-25

User requested deploying all completed changes to Dokploy. Existing `development`
services were updated from `dev`, commit
`7e27641831f074078865cec13026090da0d0d2c9` (ANY-748, including ANY-747/749/750).
At deployment start, the user had already committed and pushed this revision;
the checkout was clean and matched `origin/dev`. No new source commit was created.

- API `fitcheck-api-dev`: temporary `/bin/sh -ec` command ran migration upgrade,
  schema check and API startup. Container `18767d25463a` reported package head0015,
  database head0015, exactly one `submitted_occurred_at` column and readiness200.
- The temporary command and both arguments were then removed, saved and deployed
  again. Final API container **`7c5746014771`** was **running / healthy** for several
  minutes, with repeated readiness200 responses under the standard Dockerfile CMD.
  Dokploy's completed deployment identifies the exact commit above.
- Worker `fitcheck-worker-dev`: deployed normally after migration. Container
  **`dbdd70dcda92`** was **running / healthy**; a read-only check returned
  `PACKAGE_HEAD 0015` and `WORKER_HEALTH True`.
- Website `fitcheck-dev`: completed build in1m34s at the same exact commit. Container
  **`20b05aa2b7cb`** was running and Next.js reported Ready. The public website rendered
  its normal account screen without an API error. This service uses its existing
  Nixpacks startup and does not expose a Docker health status in the observed UI.
- The raw ops compose is independent of these source changes: its existing backup
  and private Prometheus containers were both running (Up4days). No ops configuration,
  database container, credentials, ingress or public ports were modified.

External read-only HTTPS checks at approximately **16:26 Moscow**:

| Endpoint | Result | Evidence |
| --- | --- | --- |
| `https://dev-fitcheck.dokploy.gcexp.ru/` | 200 | Normal account UI also verified in Firefox |
| `https://dev-fitcheck-api.dokploy.gcexp.ru/health/ready` | 200 | status=ok, database=ready; request ID `1ed55c31-5b92-4ffa-b786-d9b687425ca1` |
| Website `/api/backend/v1/auth/session`, without cookies | 401 expected | request ID `663d503f-0659-45cb-99a3-1e5b699ba0ea` |

Both request IDs match the final API container logs at16:26:30 Moscow, confirming
that external readiness and the website proxy reach the final running API. The API
also logged successful POST `/internal/metrics/events`200 after the public website
was opened. Email remains unconfigured, as before. No signup, paid analysis or LLM
request was performed. This rollout covers development only. The browser was left
on the final healthy API logs, with a separate tab showing the deployed website.
