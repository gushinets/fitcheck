# ANY-735/738 Coverage Gaps Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline with TDD. User requested implementation after the shared F01 review diagnosis. Keep current checkout and prior deployment evidence; no commit/push/deploy.

**Goal:** Disabled backend telemetry must not turn successful unobserved business activity into a fully covered zero.
**Architecture:** Persist identity-free, per-runtime backend collection interruption intervals. Disabled API/worker runtimes open their own interval; graceful shutdown closes only that interval. Resumed collection cannot erase or close another runtime's interval. Unknown end after a crash stays conservative. Snapshot coverage checks every required source against overlapping interruptions and exposes the same bounded coverage in JSON/CSV. Existing event collection boundaries remain necessary.
**Tech Stack:** SQLAlchemy/PostgreSQL/Alembic, Python backend operator CLI.
**Spec:** Linear comments ANY-735 `428b6b71-ea0a-4132-9a1b-a38216389a13` and ANY-738 `6707d1a9-cadb-4c3e-a95c-e1df6eee80a3`.

## Global Constraints

- Business operations continue with telemetry disabled; no synthetic registrations or views.
- Only disposable PostgreSQL tests; no changes to development collection settings or data.
- Preserve source/environment/database scope and read-only report snapshots.
- Never infer continuity from a later event, or retroactively claim pre-patch gaps known.
- No user identifiers, secrets or business payload in interruption records.
- Marker failure is logged safely and cannot block business startup; unknown historic omissions cannot be fully recovered by this patch.

## Review Focus

- Real AuthRuntime disabled registration stays successful but report is unavailable.
- Graceful shutdown vs overlapping/abandoned disabled runtimes cannot falsely heal gaps.
- Covered period with no activity remains an available zero.
- Historical windows spanning interruptions remain limited after new delivery.
- Bounds, erasure independence and environment filtering preserve existing maintenance contracts.

### Task 1: Reproduce and preserve interruption evidence

- [x] RED PostgreSQL regression with old account_registered coverage, real disabled AuthRuntime registration, direct domain/journal counts and report assertion.
- [x] Add frozen migration0013, registry/model, safe per-runtime interruption lifecycle in API/worker.
- [x] Load bounded source/env interruption intervals; Rows.add marks overlaps unavailable with explicit timestamps/reason. GREEN original regression.

### Task 2: Boundary and regression controls

- [x] All-period disable, internal gap, resumption and historical reread; pre/post-covered zero.
- [x] Concurrent disabled runtime, missing close, scope isolation, empty-action disabled period.
- [x] JSON/CSV availability/reason/coverage equivalence through CLI; failure of marker storage cannot block registration.
- [x] Retain closed interruption history for180d using existing global maintenance batch budget; test boundary/retention; migration roundtrip/schema drift.

### Task 3: Verification and handoff

- [x] Full backend/PostgreSQL suite and artifact/diff checks.
- [x] Independent final read-only review; fix important findings with RED/GREEN and rerun suite.
- [x] Record deployment migration0013 and explicit limits for crashes, storage failures and historical gaps. Preserve earlier evidence.
