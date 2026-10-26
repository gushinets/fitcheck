# ANY-738 — returned review fixes, 2026-10-24

Addresses Linear comment `6423c19b-26d2-405d-9146-8be3221ed4a0`.
Changes are local and uncommitted; this patch has not been deployed.

## Result and evidence

Technical job cleanup now archives minimal verified analysis-operation evidence
in the same transaction before removing the job link. Reports use the original
operation ID, timestamps and guest/account mode after cleanup. Actual PostgreSQL
cleanup tests preserve activation, calendar D30 and feedback at 100% (1/1);
completed but unopened results remain unactivated. Tests also cover rollback on
archive failure, replay, guest claim, analysis/account deletion and visitor erasure.
No client event creates operation proof. Existing provider call totals, tokens
and spend remain unchanged after cleanup.

Current server reports now include `session_frequency` and
`session_duration_seconds` for visitor/all scopes in JSON and CSV. Frequency
divides observed session starts among active visitors by distinct active visitors
with useful client actions in the period. Duration is the p50 of per-session
foreground pulse sums, with each pulse capped at 30 seconds and event deliveries
deduplicated. The one-visitor, one-session, 15-second fixture produces 1 and 15.
Missing source coverage or missing observations produce unavailable rows with
reasons. Legacy local registration funnels are not restored.

Proof expires after the analytics retention window, except while a still-retained
view/feedback event references it. This keeps a late first view verifiable for
that observation's own retention period. A partial index supports reference
lookups. Analysis deletion always cascades; account ownership is read from the
current analysis, without copying owner identifiers into proof. Expiration shares
the existing maintenance batch limit.

Validation on a disposable local PostgreSQL database:

- Full backend suite: **1078 passed, 5 skipped**, one existing SDK/Pydantic warning.
- Focused PostgreSQL controls: 33 passed, including migration roundtrip/schema drift.
- Formula controls: 12 passed.
- OpenAPI and generated TypeScript artifacts are current.
- Independent final code review: no findings.

## Development deployment

Deploy the backend image containing migration **0012**. In the Dokploy development
API container terminal (`api-dev`), run each command separately against its
configured development database:

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade
/app/.venv/bin/python -m fitcheck_backend.storage.migrate check
```

Expected check output: `No new upgrade operations detected.` Application startup
does not apply migrations automatically. Start/restart API and worker using the
same updated backend version after migration. Check `/health/ready` returns 200.
No new environment variables or frontend changes are required.

Migration 0012 adds the proof table and result-reference index. It does not
reconstruct already-pruned operation links: unverifiable historical results stay
unknown. Existing linked successful results are archived by subsequent technical
cleanup. No live destructive cleanup, SMTP workaround or paid LLM request was
performed. Positive live registration/claim acceptance remains unverified without
SMTP. Prior b9eab77 deployment evidence is retained separately and does not verify
this new patch; post-deployment checks are pending.

## Post-deployment check — 2026-10-24 12:15–12:16 UTC

User reports deployment completed. Local checkout is clean at `d3344a5`
(`fix: ANY-738`); the running image and database revision are not independently
confirmed. External read-only requests returned:

- Development website `/`: HTTP 200.
- Development API `/health/ready`: HTTP 502, `Bad Gateway`.
- Development API `/health/live`: HTTP 502, `Bad Gateway`.

Rollout acceptance is blocked on API availability. These proxy responses do not
identify whether the cause is container startup, routing, or another deployment
issue. Application logs and migration check output are needed; no successful
live check of the new report behavior is claimed.

### Recheck — 2026-10-24 12:17 UTC

User reran migration upgrade/check in the API container; supplied check output:
`No new upgrade operations detected.` Fresh external requests now return HTTP 200
for both `/health/live` and `/health/ready`. Readiness reports database `ready`
and email `unconfigured`. The earlier API availability blocker is resolved.
Running image/worker version and live report regression scenarios have not been
independently confirmed by these health checks.

### Supplied deployed JSON report

Parsed the user's API-container export for development/all, Europe/Moscow,
2026-10-10T12:19:54.867379Z through 2026-10-24T12:19:54.867379Z: 183 rows.
Both restored server_v2 session rows are present. Session frequency retains
numerator 13 and denominator 3; duration has 18 observed session samples and the
30-second pulse cap. Both are unavailable for the requested period, with explicit
history coverage reasons: website-client data_start is October 16, later than
the requested October 10 start. Their null values must not be reported as zero
or as complete-period session estimates.

Account activation has no mature registration cohort; current feedback has no
successful linked analysis cohort. The report shows one failed backend guest
analysis, zero successful backend guest analyses and one backend provider attempt.
These are report observations, not an independent database reconciliation. CSV
contents and the positive registration/view/feedback chain remain unverified.
