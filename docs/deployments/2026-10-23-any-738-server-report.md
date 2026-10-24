# ANY-738 — server-backed JSON/CSV report

Prepared on top of `6d020b4` (ANY-737), in the existing dev checkout. No commit,
push, deployment or live metrics mutation was performed for ANY-738. The earlier
ANY-737 rollout evidence is preserved separately.

## Result

The operator report now uses server_v2 product formulas. Account registrations
come from distinct account_registered facts. Visitor conversions additionally
require registered identity evidence. A login is not a new registration, and
legacy local_registration_completed does not establish server registrations.

The demo funnel has page -> proven guest input -> observed request -> proven
result view stages, tied to the same original guest. Visit/demo conversion and
account activation use seven-day half-open windows and mature cohorts. Product
activation and TTV use a verified VIEW with analysisId -> job -> current owner
and ANY-737 temporal identity agreement. Completion is a separate technical
metric; no completion/backfill is substituted for a view or observed return.
A transferred guest job keeps its original guest operation partition and stable
job/result IDs. It never becomes another account-created analysis after claim.

Account activation is conditional on confirmed identity coverage, with excluded
unlinked registrations, immature anchors and unknown-view reasons recorded.
Observed subsets/lower bounds are labeled. Missing proof/source/history/scope
returns null/unavailable when a zero would be misleading. Retention D7/D30 uses
complete calendar days in the requested timezone and reports immature/excluded
first-view cohorts. Original journal rows are not changed.

Saved feedback uses the current AnalysisAnnotation state for current
account-owned successful linked analyses CREATED in the report period. The
snapshot time and cohort are explicit: this is not state at historical report
end, full edit history, status-transition history or model accuracy. Notes and
user text are not loaded into metric projections. Correction edits replace the
sample; deleting feedback removes it. Imported/unlinked outcomes are excluded
and counted. Missing predictions cannot become zero correction differences.

Provider attempts, tokens, currencies and costs remain independent projections.
Backend financial totals retain deployment-wide guest costs as well as account
costs; coverage explicitly distinguishes deployment spending from person counts.
Guest usage intensity is unavailable because there is no proven operation-to-
active-visitor population linkage; it must not publish an available 0/N.

## Verification

- Exact PostgreSQL controls cover viewed vs unopened completion, failed jobs,
  registration with/without demo, claim transfer, repeated delivery/view,
  missing/foreign result and job, overlapping sessions, account erasure, source
  scope, immature cohorts and feedback save/edit/delete.
- JSON and CSV CLI controls compare row identities and every value, numerator and
  denominator. Financial control retains 2 attempts, 200 input tokens and USD2.50
  despite repeated views. No raw owner/analysis IDs or feedback notes in output.
- Current pure formula controls pin 7-day exclusion, ordered same-guest funnel,
  observed return vs reconstructed completion, missing sources, late login and
  missing prediction. Existing legacy calculation callers stay separate.
- The first full regression found five failures. Backfill onboarding/email
  calculations were corrected to use exact committed live/reconstructed actions
  with backfill completion/retention coverage; those actions do not become product
  return activity. Old completion-based activation expectations were updated.
- Independent read-only final review found an important guest usage false zero
  and a retention immature-count omission. Both were reproduced RED and fixed
  GREEN; the latter was treated as required coverage, not deferred polish.
- Final full backend: **1065 passed, 5 skipped**, one existing SDK/Pydantic warning; migration roundtrip/drift tests included.
- OpenAPI and generated TypeScript drift checks passed. No frontend code changed;
  frontend build/lint/test reruns are not required for this backend-only change.

## Deployment and acceptance

Deploy matching API/worker backend image containing this report code. Schema
remains **0011**; ANY-738 adds no migration or new environment variable. The
existing FITCHECK_METRICS_DATABASE_ENVIRONMENT must match `development` to allow
current domain projections; otherwise those rows deliberately show unavailable.
The website relay from ANY-737 does not need another change for ANY-738.

In the Dokploy development API container terminal, render a read-only 14-day
report in both formats using the SAME period:

```sh
/app/.venv/bin/python - <<'PY'
from datetime import datetime, UTC, timedelta
from fitcheck_backend.metrics.__main__ import main
end = datetime.now(UTC)
args = ['report', '--start', (end-timedelta(days=14)).isoformat(),
        '--end', end.isoformat(), '--environment', 'development',
        '--population', 'all', '--timezone', 'Europe/Moscow']
for format in ('json', 'csv'):
    code = main(args + ['--format', format, '--output', '/tmp/any738-report.'+format])
    if code:
        raise SystemExit(code)
print('/tmp/any738-report.json')
print('/tmp/any738-report.csv')
PY
```

Each build uses its own read-only repeatable-read snapshot; saved state may change
between the two builds and snapshot times record that. No backfill or cleanup is
needed just to render this report. Do not interpret unavailable as a numerical
zero, and do not add independently partitioned live/reconstructed rows blindly.

Development deployment and reconciliation of the available rows were completed
after rollout (see the post-deployment record below). A successful live control
chain remains pending. The agreed deployment environment is Dokploy development; disposable
local PostgreSQL is the automated control environment. SMTP remains unconfigured,
so no live registration/verified claim acceptance is claimed. The post-deployment record distinguishes the available-data reconciliation from
the successful registration/claim control chain; the latter must not be claimed
as exercised in development, even though local formula controls are complete.

## Decisions and limits

- First-page time may precede newly issued cookie time within the existing
  collector's five-minute tolerance, only with server receipt before the
  registration and only at the initial cookie floor. Prior-account boundaries
  remain strict. This preserves ordinary first visits; a mistake here could
  grant an incorrect first-touch conversion, so a boundary regression is pinned.
- Financial rows retain the existing backend deployment scope, including guests,
  and state it in coverage. This preserves spend and the existing row shape;
  consumers must read that scope instead of treating costs as person counts.

## Post-deployment verification — 2026-10-23

User deployed the change. Dokploy deployment lists for both API and worker show
Done at `b9eab77fd282416cc05ea3de5dc765b2d3caa156` (ANY-738).
Development API `/health/ready` returned 200 with database ready and email
unconfigured. API container `ca2d95156cd6` reports packaged schema head0011,
metrics enabled, metrics environment development and database scope development.

Ran the packaged CLI in the deployed API container through the existing Dokploy
terminal. Both JSON and CSV returned exit0 and were written to
`/tmp/any738-report.json` and `/tmp/any738-report.csv` in that container.
The shared period was `[2026-10-09T19:17:43.972515+00:00,
2026-10-23T19:17:43.972515+00:00)` in Europe/Moscow. Both contain **181 rows**;
metric/dimensions and every value/numerator/denominator matched exactly. The
current product rows declare server_v2; unchanged financial/other rows retain
their existing calculation basis.

A separate read-only repeatable-read transaction with a 5-second statement
limit reconciled the same period against current journal/domain aggregates:

| Control | Direct database | Deployed report |
| --- | --- | --- |
| Original guest analysis jobs | 1 failed | 1 technical error, 0 successes; success rate0/1 |
| Saved analyses / corrections | 0 / 0 | feedback has no eligible cohort; unavailable |
| Provider calls | 1; known input/output token sums0/0 | backend provider_attempts1, available |
| Recorded identity transitions | 0 | no attributed registration/activation invented |
| Recorded account_registered facts in period | 0 | missing source coverage shown as unavailable, not an asserted registration count0 |
| Proven demo observations | vacancy_input_started2; extraction_requested1 | no proven result view or successful product activation invented |

The journal also contains preexisting website-client observations (15 page views,
18 session starts, 38 activity pulses, 3 history views, 3 vacancy inputs,
2 extraction requests, 2 analysis requests) and website-server terminal facts
(2 analyses and 1 extraction). Those remain their own provenance; they are not
mapped to a nonexistent current saved analysis or account identity.

The 14-day period exceeds available observation coverage. Current registrations
and visitor activation therefore report unavailable with a source/history reason;
account activation has no mature registration cohort. Reconstructed activation
explicitly reports incomplete backfill coverage. These are expected coverage
limits, not failed CLI execution and not numerical zero product conversion.

No deployment/database mutation, backfill, cleanup, account creation, email or
provider request was performed during this verification. Only read-only queries
and report files in the API container's temporary directory were used.

Deployment/report smoke and reconciliation for AVAILABLE development rows have
passed. The environment still has no successful account registration/claim/result
chain to reconcile. Positive end-to-end registration/claim and feedback formula
controls remain the automated PostgreSQL evidence; a successful live control
chain is pending suitable account/email setup and must not be claimed as tested.
