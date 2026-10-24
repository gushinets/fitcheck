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
