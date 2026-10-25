# ANY-749 — provider operation linkage after job cleanup

Prepared 2026-10-25 on top of `b494c7a` (ANY-750). Changes are local; no deployment or live database mutation has been performed.

## Behavior

Physical provider calls now carry a nullable UUID `operation_id` independently of `job_id`. For a job-backed call the durable UUID is the validated job ID, shared across generation, audit, transport retries and worker execution contexts. Calls without a job use the existing operation-context UUID. It has no foreign key to the technical job.

Migration **0014** fills the durable field only from an intact same-owner job link. Already-null job links remain unknown; request keys, result proof and deleted account/visitor data are not used to reconstruct them. New admissions write the durable ID. Technical cleanup also captures a surviving job ID before clearing `job_id`, covering transitional calls written by an older worker after migration. Reports prefer the durable ID and fall back to a live job ID.

Owner deletion clears `operation_id`, `job_id`, `owner_id` and `request_key` through the existing database ledger-anonymization trigger. Constraints reject an operation ID on an anonymous call and reject a durable ID conflicting with an attached job. Guest claim changes ownership without changing operation identity or the original guest operation partition. Product result/view/activation proof is unchanged.

## Metric semantics and limits

`attempts_per_operation` uses all observed physical calls linked to operations **created in the selected period**, divided by the count of those operations. `cost_per_success` divides known spend for those created operations, including failed attempts/audits, by their observed successful operation count. Currencies remain separate; unknown pricing is explicitly counted and does not become zero spend. Calls and operations are projected independently, avoiding one-to-many multiplication.

For backend ratios, a period call without verifiable operation/creation-cohort membership makes the affected value `null`, `available=false`, with reason `Provider call operation linkage or creation-cohort membership is unverifiable`. Partial observed numerators/denominators remain in the row. Coverage includes `unlinked_period_calls`, `unverifiable_cohort_calls`, `operation_linkage` and `linkage_completeness`. A recognized purpose restricts the impact to its operation kind; an unknown legacy purpose conservatively affects all backend kinds. Known operations outside the creation cohort are excluded without making it unavailable.

The durable UUID does **not** recreate missing creation/outcome facts. For example, a failed guest analysis without a saved result or retained journal creation evidence loses its cohort proof when its technical job is pruned. Its ratio becomes explicitly unavailable; physical call totals, tokens and spend remain independent and usable. The same applies when result history/proof was erased or expired. Existing website-server observed-only report behavior is unchanged.

The exact ANY-749 control remains stable before/after actual cleanup: two successful account analyses, one physical USD1.25 call each, one old job and one retained job → 2 calls, USD2.50 total, 1 attempt/operation, USD1.25/success. Repeated cleanup does not change these values or add operations. No paid provider requests are needed for verification.

## Deployment

No new environment variables or website deployment are required. Prepare matching API/worker backend images containing revision **0014**. Pause old workers and maintenance jobs during migration/rollout; an old cleanup implementation cannot preserve links on calls written after the one-time migration backfill.

In the updated Dokploy development API container terminal, run separately against its configured development database:

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade
```

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate check
```

Expected check: `No new upgrade operations detected.` Application startup does not migrate automatically. Restart API and worker on the matching updated backend version after migration; `/health/ready` must return 200. The migration is transactional and uses the existing migration runner lock. It updates intact provider-call links; it does not run retention, alter financial usage values or repair already-pruned associations.

Optional aggregate SQL verification, without exporting user identifiers:

```sql
SELECT
  count(*) FILTER (WHERE job_id IS NOT NULL AND operation_id IS NULL) AS live_job_fallback_calls,
  count(*) FILTER (WHERE owner_id IS NOT NULL AND job_id IS NULL AND operation_id IS NULL) AS unlinked_owned_calls,
  count(*) FILTER (WHERE owner_id IS NULL AND operation_id IS NOT NULL) AS invalid_anonymous_links
FROM provider_calls;
```

Immediately after migration, intact links are filled and `invalid_anonymous_links` must be zero. `unlinked_owned_calls` may be nonzero for historical missing associations; this is a coverage limit, not a prompt to reconstruct them. Render the normal operator JSON/CSV reports for the same period and environment; inspect value/availability and coverage together. Do not run synthetic retention against development/production to validate this change.

For rollback, use a matching older backend and a verified backup. Downgrade to 0013 drops the durable UUID field and restores the prior anonymization function; physical calls and financial amounts survive, but archived operation links cannot be recovered after that downgrade unless a backup or intact job link remains. Stop new code before a schema downgrade. Rollback is not part of ordinary rollout.

## Local verification

All database controls use the guarded disposable `fitcheck_test` PostgreSQL; no live cleanup, email or provider request was performed.

- Full default backend suite: **691 passed, 2 skipped**; 426 integration tests deselected. One existing SDK/Pydantic ReadOnly warning remains.
- Full integration suite before the final four additional edge controls: **419 passed, 3 skipped**. Includes upgrade/downgrade, schema drift, ownership, budgets, claim, cleanup, erasure and HTTP readiness.
- Targeted ANY-749 controls: **17 passed**, additionally covering live CLI JSON/CSV before/after cleanup, 1/3 attempts per job, mixed currency/unknown pricing, claim before/after cleanup, erased result/account, legacy links, failed guest proof loss, no-job contexts and database constraints.
- Wheel installation confirms packaged migration head 0014. Explicit migration/readiness fixture heads were updated from 0013 to 0014.
- Independent read-only review: no remaining Important/Critical findings; the failed-guest proof boundary is documented and tested.

Run the unit suite from `backend`:

```sh
.venv/bin/python -m pytest -q
```

For PostgreSQL, set `FITCHECK_TEST_DATABASE_URL` to a disposable database whose name ends in `_test` (the fixtures enforce this) and run:

```sh
.venv/bin/python -m pytest tests -m integration -q
```

Focused control:

```sh
.venv/bin/python -m pytest tests/integration/test_provider_operation_retention.py -m integration -q
```

The first controls reproduced the exact 1→0.5 attempts ratio regression and missing legacy unavailability before production changes. Initial sandbox runs could not connect to PostgreSQL or fetch wheel build dependencies; the corresponding checks passed with the required local DB/network permissions.
