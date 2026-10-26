# ANY-738 Review Fixes Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline and TDD. User approved “делай” after reviewing the Linear comment of 2026-10-24. Keep the existing dev checkout; no commit/push/deploy. Preserve previous deployment evidence.

**Goal:** Keep verified result/operation facts across technical job cleanup and restore current-report session metrics.
**Architecture:** An additive analysis-operation proof table survives job deletion but cascades with the analysis. The maintenance transaction inserts verified minimal proof before detaching/deleting jobs. Current report reads live job or archived proof under the same domain database scope. Session rows use observed visitor/client session signals independently of account attribution and legacy registration.
**Tech Stack:** Python, SQLAlchemy/PostgreSQL/Alembic, existing JSON/CSV CLI.
**Spec:** Linear ANY-738 comment6423c19b-26d2-405d-9146-8be3221ed4a0; original spec docs/superpowers/specs/2026-10-23-any-738-server-report-design.md.

## Global Constraints

No completion-as-view. No SMTP bypass, paid calls, or live cleanup. No untrusted
client IDs as proof. No raw notes/tokens/email in proof or reports. No proof
recovery for already erased or unverifiable historical results. User deletion
continues to cascade. Keep bounded 180-day analytics retention and maintenance
batch ceiling. Preserve current annotations as current state, not edit history.

## Review Focus

- Real cleanup must preserve activation100%(1/1), D30100%(1/1), feedback100%(1/1).
- Completed but unopened result stays unactivated after cleanup.
- Analysis/account deletion and visitor erasure cannot reconstruct associations.
- Original guest mode/operation survives claim and cleanup once, without duplicating jobs/costs.
- Session pulses deduplicate event deliveries, cap at30 seconds each, and never infer wall time.

### Task 1: Durable verified operation proof

Files: new storage/analysis_operation.py; migrations/versions/0012_analysis_operation.py;
metrics/analysis_operation.py; operations/retention.py; metrics/server_projection.py;
metrics/retention.py; model registry/head assertions; new PostgreSQL regression tests.
Interface: AnalysisOperationProof keyed/FK analysis_id CASCADE, unique original
job_id WITHOUT a job FK, original mode, job_created_at, finished_at. No owner ID
copy: current analysis ownership remains authority. archive_analysis_operations
performs INSERT SELECT from same-owner successful analysis jobs, before their
links are nulled, in the cleanup transaction. Failure rolls back pruning. Proof
expiry uses finished_at180d, preserving evidence referenced by a still-retained
result observation, and shares the global metrics cleanup budget.
Reader coalesces live job/proof fields and retains stable original operation IDs;
archived successful operations keep their original account/guest partition.
- [x] Add/run RED integration report before/after actual cleanup, viewed/unopened,
  correction state and surviving journal/result assertions.
- [x] Implement model/frozen migration, archival and read projection. Run GREEN.
- [x] Add/run erasure, claim/idempotence, failed archival atomicity, bounded expiry,
  wrong database scope and migration roundtrip/drift controls.

### Task 2: Current session metrics

Files: metrics/server_calculations.py; tests/metrics/test_server_calculations.py;
integration/test_metrics_server_report.py.
Interface: session_metrics(out) emits visitor session_frequency and
session_duration_seconds p50 for visitor/all. Active denominator = distinct
observed visitor IDs with useful CLIENT actions in period (profile_saved,
analysis_result_viewed, history_viewed, skills_accepted, feedback_saved), independent
of successful account attribution. Frequency = distinct observed(visitor,session)
starts among these active visitors / active visitors. Duration = p50 of per-session
summed foreground pulses, max30,000ms per pulse. Deduplicate event_id. No active
cohort or no pulses => unavailable reason; missing source coverage stays unavailable.
- [x] Add/run RED server_backed=True control1 visitor/1 session/15,000ms =>1 and15s.
- [x] Implement rows with explicit observed coverage and sources; test duplicates,
  multiple sessions, pulse cap, absent source and no legacy funnel restoration.
- [x] Verify both metrics in actual PostgreSQL/CLI JSON/CSV output.

### Task 3: Final regression/review

- [x] Full backend/PostgreSQL suite, schema head0012 roundtrip/drift, public
  artifact checks, diff check. No frontend implementation changes planned.
- [x] Fresh independent read-only final review; important findings RED→GREEN,
  full green suite after fixes. Record deployment/migration instructions and
  which prior live checks do not verify this new patch.
