# FitCheck metrics development rollout — draft evidence record

Original task date: **2026-10-14**. Continuation client date: **2026-10-15**.
Target: existing Dokploy FitCheck **development** services. **Deployment pending.**
This record is prepared for review before remote changes; it is not proof of CI,
live schema head, health, ingestion, erasure or deployment. The controller will append
exact external evidence after executing the rollout. No OpenAI switch or paid model
calls are part of this rollout. Existing provider/source configuration is preserved.

Operational reference: [backend telemetry and reports](../../backend/README.md#telemetry-and-operator-reports),
[website configuration](../../README.md#deployment),
[metrics plan](../superpowers/plans/2026-10-14-fitcheck-metrics.md),
[companion OpenAI plan](../superpowers/plans/2026-10-14-fitcheck-openai-migration.md).

## Inspected deployment context

Dashboard: `https://dokploy.gcexp.ru`. User selected development and restored login.
Read-only inspection observed five running services. No remote settings, secrets or
deployments had been mutated at documentation preparation time.

| Resource | Observed identifier / configuration |
| --- | --- |
| Project / development environment | `mrgiwqABnA-V8OfHEZFsL` / `YIpwNok_LUdsK3u8RUDa7` |
| API | `4Dfp-p3ua4kBSxLZ_mczn`; `app-program-open-source-hard-drive-w7n8it`; backend/Dockerfile, context backend |
| Worker | `uGz_HiVcXoTo1Rid214vn`; `fitcheck-fitcheckworkerdev-x8lwxi`; backend/Dockerfile.worker, context backend |
| Website | `4cwEJ5gtixQ_Dcxm8lGnM`; `fitcheck-dev-xxfvyz`; Nixpacks |
| Repository / trigger | `NikitaPotapovIt/fitcheck`, `dev`, GitHub On Push |
| Initial autodeploy | API ON; worker ON (clean cache OFF); website ON |
| Watch paths | API/worker `backend/**`; website none listed |

These observations do not establish a separate production deployment. Capture any
changed settings before restoring them; preserve unrelated settings and all secrets.

## Local verification evidence available before rollout

Runtime implementation head at handoff: `09724ae` (Task 7 reviewed fix); frontend
unchanged since `79132e7`. These are local verification results reported by the
controller, not CI results for a deployed runtime commit. Latest predeployment
verification is dated 2026-10-15. GitHub authentication/repository access was verified
without printing credentials; no push or remote configuration/deployment occurred.

| Check | Actual evidence / qualification |
| --- | --- |
| Full backend PostgreSQL suite | 639 passed, 1 skipped in 26.19s at `22bcfbe`, before the final Task 7 fix. |
| Final Task 7 fix covering checks | 47 passed in 0.70s at `09724ae`, metrics + report integration. Pure RED 3 failed → GREEN 23 passed. Requested PG RED ran after fix (2 passed), so is GREEN only. |
| Frontend full suite | 356 passed, 3 optional live tests skipped before the final history-clear epoch fix; focused 16 passed covers that final fix at `79132e7`. |
| Frontend production build | `node node_modules/next/dist/bin/next build --webpack` passed at `79132e7`: seven static pages, Proxy, four dynamic API routes. `/` prerendered. |
| Lint / generated types / TypeScript | Full ESLint and generated backend TS `--check` passed at `79132e7`; final focused TypeScript/lint checks passed. Frontend unchanged afterward. |
| API image | Final rebuild at `09724ae` passed on 2026-10-15: `fitcheck-metrics-api:20261015`, digest `sha256:d6fd6b776c52aec907c46b9c82f2fba65c0afe5fbc1bf49d61180f2dcc503654`. |
| Worker image | Build running at latest 2026-10-15 update; result pending. |
| Schema / contracts | Task 4 disposable PostgreSQL migration 0004→0005 preservation/index/erasure checks passed (24); Alembic metadata check found no new operations; OpenAPI/generated TS drift clean. Latest 2026-10-15 OpenAPI `--check` is current; actual Alembic check found no new upgrade operations against guarded disposable test DB at 0005. No development schema evidence yet. |

Backend full command (from backend/, disposable database only):

```sh
env FITCHECK_TEST_DATABASE_URL=postgresql+psycopg://fitcheck_test:fitcheck_test@127.0.0.1:55464/fitcheck_test uv run --locked pytest -m 'integration or not integration' -q --maxfail=1 --tb=short
```

The first full Task 7 run stopped at 270 passed / 1 skipped in 6.94s:
`tests/integration/test_job_publication.py::test_failure_publication_reconciles_stranded_started_call`
received `None` while preparing a lease immediately after admission. Exact isolated
rerun passed (1 in 0.33s), then full rerun passed as above. The cause remains
**unproven**; no code/test was changed for this result. Final whole-branch review
must triage it. A suspected DB-clock/application-available-at boundary is not a
confirmed diagnosis. Deferred review also includes successful-publication failure
injection verifying neither result nor success fact remains. Do not silently omit
either item from the final review decision.

## Planned rollout order — execution and evidence still pending

1. Finish whole-branch review and verified fixes; record final tests and API/worker
   images. Commit exact runtime code. Before pushing, control all three autodeploy
   settings so new code cannot start ahead of migrations; record original states.
   Push `dev` and verify CI for the exact runtime SHA.
2. Apply additive **0004_metrics + 0005_metrics_erasure**, preserving frozen
   `0001`–`0004`. Verify runner code and actual packaged migration paths. The old
   live image may contain only `0003`; its plain `upgrade head` cannot see new files.
   Prefer a supported new-image one-off migration runner. If unavailable, review an
   exact committed migration transfer to a writable temporary copy of the old tree,
   preserving `migration_connection` advisory locking and explicit script location;
   do not overwrite packaged code. Record actual method, checks and resulting head.
3. Deploy collector with telemetry disabled. Configure independent high-entropy
   bridge and cookie secrets in supported stores, matching bridge credentials and
   explicit website/collector environment. Never print credentials or reuse a
   provider key. Configure API/worker database scope independently as development.
4. Perform the real-bridge synthetic check with a concrete excluded scope. Both
   website and collector have one server-trusted environment; client payload cannot
   select test scope. Proposed staging: temporarily set website and collector to
   `test`, keep backend domain collection disabled, rebuild/deploy website, submit a
   named non-PII event twice and confirm one stored fact plus duplicate behavior via
   operator report/aggregate inspection. Controller must confirm the supported
   enablement arrangement before execution; no new public test endpoint or flag.
5. Record only the named synthetic facts and erase only those through a supported,
   explicitly scoped mechanism. The cleanup CLI has no scope selector and is not
   a synthetic-scope deletion tool. No development reset. Capture exact evidence;
   pending until an actual supported mechanism is verified.
6. Configure website and collector to `development`, retaining independent
   `FITCHECK_METRICS_DATABASE_ENVIRONMENT=development`; enable backend lifecycle
   telemetry on API/worker. Mirror campaign codes (website comma-separated, backend
   JSON array). Rebuild/deploy website: static enabled/campaign props require build
   environment, and runtime reload alone is insufficient. Secrets stay server-only.
7. Verify packaged schema head and API readiness/liveness plus worker health.
   Observe one real non-paid website action and its development aggregate. Verify
   no public report access. Record exact UTC times, runtime SHA, CI run, migrations,
   aggregate result/coverage and erasure proof without raw identifiers or secrets.
   Restore intended autodeploy settings after ordering is safe.
8. Append actual evidence below and only then close the metrics plan. Continue the
   companion OpenAI plan afterward, using next-free `0006` if pricing needs schema.

Local provider tests remain skipped; no live model coverage is claimed. Report
population `all` keeps visitor/account provenance separate and does not count a
visitor and backend account as one person. Legacy database scope cannot prove
historical per-row environments; missing scope is unavailable. Collection start,
received-at journal retention, erasure and failed delivery limit cohort coverage.
See backend operations for exact formulas and CLI examples.

## Rollback

Disable API/worker `FITCHECK_METRICS_ENABLED`, remove website bridge configuration,
and rebuild/redeploy to update static enabled props. Preserve domain data, provider
and website ledgers, and additive schema. Stop any independently installed cleanup
schedule if needed. No database downgrade/reset and no provider switch. Existing
observations remain available to the operator; disabled collection creates a gap
and process-local counters cannot prove its full size.

## External evidence to append after execution

Pending: final review dispositions (including deferred minor and transient test),
final verification commands/results, exact runtime/docs SHAs, CI run URL/conclusion,
image build/deployment identifiers, restored setting states, actual migration runner
and live head, API/worker health timestamps, named synthetic scope/duplicate/erasure
proof, public-report rejection, development non-paid observation and aggregate
coverage, remaining limitations. No item in this list is currently asserted complete.

## Approved implementation rulings and cost if wrong

The following decisions are retained verbatim from the execution ledger so the
ignored orchestration workspace can later be archived. Later independent database
scope wording refines the earlier scope decision; it does not change past rows.

1. enforce hard signed visitor issuance expiry at 180 days in Task 3, and raw journal retention by received_at in Task 4 — first-touch journal must not expire before the cookie identity and no indefinite sliding visitor lifetime is specified — cost if wrong: active visitors rotate at 180 days and long-term attribution needs a future durable table.

2. root handles escalated verification and Git writes while implementers prepare tests/code/reports — worker approval stalled 583 seconds without output, whereas root approval is visible to user — cost if wrong: extra orchestration handoffs; independent code review still gates every task.

3. allow equivalent installed Node frontend runners in sandbox (Vitest4.1.11/TypeScript5.7.3 verified, same pnpm-resolved binaries) — avoids unnecessary packageManager registry fetching after signed pnpm retry succeeded, without disabling verification or changing dependencies — cost if wrong: command labels differ from plan; final verification records exact equivalent executables. Escalate any actual sandbox failure normally.

4. Task3 injectable factory lives in app/api/metrics/handler.ts, route.ts exports only allowed Next HTTP/runtime exports — installed Next build validates route module exports — cost if wrong: one additional focused module to maintain.

5. add explicit anonymous backend_server account_deleted (nullable subject, no owner/session/operation/domain key, empty properties) plus environment-scoped erased visitor digests retained 181 days, via additive 0005_metrics_erasure — required deletion aggregate cannot survive current owner FK cascade, and late server facts/new call IDs otherwise restore deleted association — cost if wrong: additional migration/contract surface and one extra day of opaque revocation digests; OpenAI usage migration shifts to next free revision 0006 if needed. Preserve 0004 frozen.

6. lifecycle/backfill excludes guest-only owners and erases claimed guest associations defensively — spec defines backend account population through real User records, not guest records — cost if wrong: guest-only historic activity remains unavailable rather than counted as accounts.

7. metrics-emitting queue/recovery acquires nonblocking Owner KEY SHARE before Job FOR UPDATE and revalidates candidate; publication acquires owner lock before fenced job — new owner-FK events otherwise invert account-deletion lock order; skipping facts after a committed transition would lose legitimate facts during guest claim — cost if wrong: up to 100 candidate owner/job query pairs, temporary skip of a fully busy 100-candidate prefix, bounded publication owner wait. Deterministic concurrent owner-lock regression added.

8. link server analysis and later local views/feedback through opaque X-FitCheck-Operation-Id response header and optional local history context, keeping output DTO/API methods compatible — otherwise independent browser result UUIDs cannot substantiate feedback denominators or operation correlation — cost if wrong: optional client API/history metadata surface; legacy history remains unlinked.

9. allocate visitor cookie on initial document GET / using minimal configured Next proxy, with no network and no valid-cookie rewrite — concurrent first browser telemetry/product calls otherwise mint two visitors and split accounting — cost if wrong: additional request boundary and document-cookie cache behavior to verify; direct API callers still use fallback identity.

10. retain existing total/cached input token contract, derive uncached only when both known and consistent; no extra field now — current ledger/schema has no independent uncached field and missing totals cannot be inferred safely — cost if wrong: cache-miss-only upstream metadata unavailable until contract extension.

11. include unscoped legacy backend domain/provider rows only under an explicitly configured deployment database environment matching report selection; missing scope makes those metrics unavailable, and report records historical per-row environment limitation — legacy accounting lacks environment and deletion erases join keys, so user-selected report environment cannot safely attribute rows — cost if wrong: mixed-environment legacy databases need future migration/reconciliation; no arbitrary cross-env aggregate offered.

12. permit independently known raw token subdivisions with absent totals in WebsiteAttempt validation; enforce subdivision<=total whenever total is known — preserving actual partial usage otherwise cannot pass collector, and absent total must remain unknown for costing — cost if wrong: partial usage consumers must check required totals before estimating costs; no inferred zero/total.

13. website METRICS_CAMPAIGN_CODES is a comma-separated server-only configuration of public dimension codes, mirrored to backend JSON-list FITCHECK_METRICS_CAMPAIGN_CODES; filter bounded safe codes before passing public allowlist — frontend requires known values before arbitrary URL input enters queue and existing backend uses its own settings parser — cost if wrong: operators must keep two equivalent list encodings aligned; collector still normalizes unknown/stale values to other.

14. strengthen legacy database scope to independent FITCHECK_METRICS_DATABASE_ENVIRONMENT, not collector metrics_environment — collector may temporarily be test while physical DB and historical calls are development; shared setting would relabel history — cost if wrong: one explicit deployment setting needed, backend legacy metrics unavailable until configured. This refines the earlier explicit-database-scope ruling; no default inference or schema rewrite.

15. observed D7/D30 retention cohort requires observed registration and retained registration→first-observed-activation history, excluding uncertain-first subjects with coverage counts — earlier activation outside collection cannot be disproved, and raw retention alone must not turn old users into new activation cohorts — cost if wrong: conservative exclusion reduces sample size; website blockers/delivery remain observation limitations.
