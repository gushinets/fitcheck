# ANY-749: provider-call operation retention

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep physical-attempt and cost ratios stable across real job cleanup, while making irrecoverable historical linkage explicit.

**Architecture:** Add nullable `provider_calls.operation_id` (UUID, no job FK) in revision 0014. For job-backed calls use the validated job ID; for calls without a job use the existing operation context ID. Preserve this at creation and atomically before pruning an old job. Report projection prefers the durable ID and falls back to a live `job_id` for transitional writes. Owner deletion clears both operation and job IDs through the existing ledger trigger; do not reconstruct identities/history from request keys or proofs.

**Tech Stack:** SQLAlchemy, Alembic/PostgreSQL, pytest, existing metrics CLI JSON/CSV.

**Spec:** Linear ANY-749, fetched 2026-10-25.

## Global constraints

- Only isolated `_test` PostgreSQL receives synthetic cleanup/migration controls; no deployed environment mutation or paid provider calls.
- Revision 0014 backfills only intact same-owner job links; already-null links stay unknown. Nullable column and report fallback accommodate old workers during rollout.
- Physical call counts, token totals, currencies, unknown pricing and cost basis stay independent of operation linkage.
- For backend operation ratios, missing/unverifiable creation-cohort membership for relevant period calls makes the value unavailable with reason and coverage counts. Preserve observed partial numerators/denominators, without presenting them as complete values.
- Use purpose to restrict missing-linkage impact to the relevant operation kind; unknown purpose conservatively affects all kinds. Website-server's existing observed-only report semantics stay unchanged.
- Existing user erasure and guest claim behavior remain authoritative; durable IDs do not restore deleted analysis or account relationships.
- Current checkout is clean on dev at b494c7a (ANY-750 committed by user). Work in place; no deployment, push, merge or external issue messages.

## Review focus

- Retried/audit calls must all retain one operation ID without doubling money or counts.
- Already-anonymized or unlinked legacy rows cannot be reidentified by migration or reporting.
- Cleanup must preserve transitional calls written with null operation_id, and repeat cleanup must be idempotent.
- Guest claim before/after cleanup must not count a guest-created operation as account-created.
- JSON/CSV availability, numerator/denominator and currency separation must agree before/after maintenance.

### Task 1: Reproduce and preserve storage linkage

Files: `storage/accounting.py`, `storage/budget_repository.py`, `operations/retention.py`, migration `0014_provider_operation.py`, storage/migration integration controls.

- [x] Add and run failing PostgreSQL controls reproducing ANY-749 and verifying ledger writes, intact-link backfill, legacy nulls and owner deletion.
- [x] Add durable ID, compatibility constraints, migration/backfill and deletion trigger update; write the validated operation identity at admission and preserve it atomically before cleanup nulls job_id.
- [x] Update explicit schema-head expectations to 0014 and verify upgrade/downgrade/schema drift and distributable wheel.

### Task 2: Conservative report projection

Files: `metrics/queries.py`, `metrics/calculations.py`, report tests.

- [x] Run failing tests for stable before/after ratios and unavailable unknown membership, with unrelated kinds and mixed currencies/unknown pricing controls.
- [x] Project durable ID (fallback to live job_id); mark affected backend ratios unavailable when cohort membership is unverifiable. Keep financial totals independently usable.
- [x] Verify actual cleanup, repeated cleanup, retries, guest claim and erasure using real report JSON/CSV.

### Task 3: Verification and operator handoff

- [x] Run backend suite plus affected PostgreSQL suites; verify no schema drift and review the full diff independently.
- [x] Document migration order, legacy limitations, rollback and exact local results in a deployment note.

## Execution record

- Root cause confirmed: queries rename provider_calls.job_id to Attempt.operation_id; cleanup clears it. Existing result-operation proof keeps successful operations in the denominator. Actual provider admission already carries an operation context but only stores it inside request_key.
- Linear shared-notes tool was advertised but returned tool-not-found; issue description and current source are the evidence used.

- Task 1 complete: original cleanup regression reproduced in six report controls; durable admission/owner deletion/migration controls failed before implementation. Revision0014 adds nullable UUID, compatibility/anonymous constraints, intact-link backfill and anonymization-trigger update. Targeted migration roundtrip and schema check passed; installed wheel head is0014.
- Task 2 complete: actual cleanup/repeat cleanup, three attempts, currencies/unknown pricing and CLI JSON/CSV stay stable when cohort proof survives. Irrecoverable linkage or creation membership yields explicit unavailable affected ratios. Guest claim before/after cleanup stays in guest partition; erasure does not reconstruct result/account identity.
- Ruling: a durable call UUID cannot recreate removed creation/outcome facts (e.g. failed guest without retained result/journal). Those rows deliberately become unavailable, as allowed by ANY-749's missing-proof rule; totals remain independent. Added PostgreSQL regression and deployment limitation after independent review raised the edge.
- Task 3 complete: full default backend691passed/2skipped (426integrationdeselected); fullintegration419passed/3skipped before four final new edge controls; complete targeted ANY-749 file17passed. Pure metric formulas34passed. One existing SDK/Pydantic ReadOnly warning. Wheel network test initiallyblocked bysandboxPyPI, then passed with access. No frontend code changed, so frontend checks not rerun.
- New guest-fixture failures were synthetic setup errors (immutable analysis timestamp, then required failed-job error payload); corrected fixtures without changing production protections. All final targeted checks passed.
- Independent read-only review: no remaining Important/Critical findings under the documented surviving-cohort-proof requirement. Failed-guest limitation additionally pinned with a database control.
- Whitespace check passed. Changes remain uncommitted in current dev checkout; no deployment/push/merge/external issue writes. Deployment instructions saved in docs/deployments/2026-10-25-any-749-provider-operation-link.md.
