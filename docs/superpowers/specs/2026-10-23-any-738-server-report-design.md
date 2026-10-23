# ANY-738 — server-backed metric formulas

Status: implemented and locally verified; development rollout acceptance pending.

User approved the proposed seven-day conversion/activation window with “делай”.
Continue inline in the existing dev checkout, leave changes uncommitted for the
user's Dokploy workflow. Preserve ANY-737 deployment evidence.

## Scope and approach

Extend the existing bounded read-only CLI JSON/CSV report. Reuse ANY-736 demo
proofs and ANY-737 temporal identity projection. No new dashboard, SMTP setup,
paid calls, provider ledger changes or status/feedback history collection.
Alternative: manufacture client registration/completion-as-view events. Rejected:
those would change populations and assert observations that did not happen.
Version the changed formulas as server_v2 in coverage while preserving JSON/CSV
row shapes. Legacy local calculations remain isolated to legacy snapshot callers;
the deployed report loader always selects current server formulas.

## Formulas

All report intervals are [start,end), scoped by environment. A conversion window
is [anchor,anchor+7 days), and only fully matured anchors enter a seven-day rate.
Immature and excluded anchors are reported explicitly. Undefined denominators
produce null/unavailable with a reason, never a successful zero conversion.

- Account registrations: distinct account_registered owner facts, independently
  partitioned by backend_server/reconstructed_backend. Login is not registration.
- Visitor registration attribution: distinct visitors with a registered identity
  transition AND the matching account_registered fact. This is a visitor
  conversion count, not another account population. Anonymous history may join
  only inside the transition's anonymous_from..occurred_at segment.
- Demo funnel: unique observed visitors with page_viewed in the period; first
  period entry is anchor. Ordered page -> server-proven guest input -> request
  -> verified guest result view, within seven days. Input/request/view must belong
  to the same original guest. Request means observed request, not admission.
  Repeated deliveries/views cannot increase people or completed operations.
- Visit/demo -> registration: distinct mature period-entry visitors with a
  matching confirmed registration inside seven days and its anonymous segment;
  demo conversion additionally requires a proven demo view before registration.
- Product activation and TTV: first verified result VIEW after account registration,
  within seven days. Identity window must resolve exactly to the result's current
  account owner; flow=demo cannot count as a post-registration account view.
  Result maps analysis_id -> job_id through current domain rows. A live window,
  archived closure or erasure guard is resolved by ANY-737, never latest-login
  guessing. Missing links/ambiguous sessions remain unknown. Conditional linked
  cohorts identify excluded unlinked accounts; no completion fallback.
- Account useful activity/feature adoption/retention uses attributable observed
  client actions plus explicit live server user actions (profile save, verify).
  Job completion/backfill cannot establish product return or first view.
  D7/D30 use full calendar-day outcomes in the requested timezone. Reconstructed
  registration facts may anchor cohorts, but reconstructed jobs are not returns.
- Technical completion/latency, physical calls/tokens/cost remain separate and
  retain existing independent projections and provenance partitions.
- Feedback coverage: latest saved AnalysisAnnotation correction / distinct current
  account-owned successful analyses CREATED in the report period. Read numeric
  scores only; no notes/user text. Current owner after claim is an explicit
  snapshot cohort, not proof of account activity at the analysis creation time.
  Absolute correction differences use the stored prediction and current saved
  correction; p50/p95/distribution describe latest state, not accuracy/history.
  Historical report end does not reconstruct historical feedback: metadata names
  the current read time and analysis-creation cohort. Edits replace, deletion
  removes correction; imported/unlinked analyses are excluded and counted.
- Acquisition uses first observed page inside the confirmed anonymous segment;
  missing touch is unknown, not direct by assumption. Visitor first-touch and
  account attribution populations/provenance stay separate.

## Coverage and safety

Unknown/missing sources, mismatched deployment database scope, absent proof and
immature cohorts carry explicit reasons/counters. Source available_from/retention
floors remain necessary; verified subsets do not claim exhaustive observation.
Queries have a 100000-row ceiling and share the existing read-only repeatable-read
transaction. Read identity rows and minimal session time bounds in bulk; reuse a
pure identity projector to avoid per-visitor SQL. Anonymous erasure guards affect
windows but are not exposed as confirmed transitions. Raw IDs stay internal and
never appear in JSON/CSV. Preserve all financial rows and avoid 1:N join fanout.

## Verification

TDD for control cases: viewed demo -> registered; no-demo registration -> account
view; completed-but-unopened and failed jobs; retries/repeated views; correction
saved/edited/deleted; foreign/missing results; login/switch/overlap/erasure;
late demo delivery; source gaps, scope mismatch and immature cohorts.
Assert exact numerators/denominators, JSON/CSV parity and PostgreSQL CLI output,
plus unchanged attempts/tokens/spend. Run full backend suite and contract checks.
Use disposable PostgreSQL for automated formula controls. The agreed deployment
environment remains Dokploy development; live report/journal reconciliation is
a separate rollout step, SMTP still absent.


Implementation detail: first-page browser time may precede newly issued cookie
by the collector's accepted clock bound. Only an initial anonymous floor equal to
cookie issuance may admit such an event, and only when its server receipt falls
between cookie issuance and confirmed registration. Prior-account boundaries
remain strict. Original event timestamps stay unchanged.
