# ANY-738 Server Report Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, with a fresh final whole-change reviewer. User said “делай”; continue without intermediate approvals. Preserve existing checkout and leave uncommitted.

**Goal:** Current server-backed JSON/CSV metrics with trustworthy product views, registration links and saved feedback.
**Architecture:** Bounded independent SQL projections feed pure server_v2 aggregates. Reuse ANY-737 identity windows and ANY-736 guest proofs; financial aggregates stay independent.
**Tech Stack:** Python/FastAPI, SQLAlchemy/PostgreSQL, pytest, existing operator CLI.
**Spec:** docs/superpowers/specs/2026-10-23-any-738-server-report-design.md

## Global Constraints

Seven-day half-open mature conversion/activation windows. No false view from job
completion. No inferred identity. No notes/email/token output. No new dashboard,
SMTP/provider calls, automatic commit/push/deploy. Preserve ANY-737 evidence.

## Review Focus

- Missing and overlapping identity evidence must not grant a foreign result view.
- Deleted/switch-target accounts must not reopen attribution to another account.
- Claim and one-to-many view/feedback records must not multiply domain analyses or spend.
- Absent sources and immature cohorts must not produce misleading zero rates.
- Current annotation snapshot must not masquerade as historical feedback/return.

### Task 1: Bounded current-report projections

Files: metrics/report_types.py, queries.py, identity_queries.py, report.py;
new metrics/server_projection.py; integration/test_metrics_server_report.py.
Interfaces: Snapshot.server_backed, identities per visitor, demo proofs by event,
minimal AnalysisFact records, snapshot_at. project_identity(rows) shared by existing
identity_snapshot and bulk loader. load_server_projection(conn,options,data) reads
minimal columns only in the existing transaction.
- [x] Write/run RED tests for real analysisId/job linkage, identity windows,
  scoped bulk reads, demo proof and annotation numeric snapshot without text.
- [x] Implement bounded rich projection with no ledger fanout; run GREEN.

### Task 2: Current product formulas and coverage

Files: new metrics/server_calculations.py; calculations.py; new metrics/test_server_calculations.py.
Interfaces: calculate_server(out) produces product rows and active sets;
calculate() dispatches rich snapshots to it, then reuses technical/financial math.
Every current row includes formula_version=server_v2 and explicit cohort basis.
- [x] Write/run RED control tests for demo/account views vs completions, seven-day
  windows, identity ambiguity, unsupported result and missing history.
- [x] Implement registrations, separate funnels, viewed activation/TTV, observed
  activity/retention/acquisition and latest-state feedback. Old unavailable
  ANY-650 explanations removed from current output. Run GREEN.

### Task 3: End-to-end report verification and delivery

Files: integration/test_metrics_server_report.py, affected legacy report tests;
docs/deployments/2026-10-23-any-738-server-report.md.
- [x] Run PostgreSQL controls including CLI JSON/CSV, correction edit/delete,
  erasure, duplicate view and financial invariance; update old completion-based
  current-report expectations to viewed semantics explicitly.
- [x] Run full backend suite, API/TS drift, diff check and required frontend
  checks if frontend code changes (none planned).
- [x] Fresh read-only final review; fix important findings RED→GREEN and rerun
  affected/full suite. Record evidence and development rollout limits.
