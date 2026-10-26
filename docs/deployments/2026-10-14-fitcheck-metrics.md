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
| Worker image | Build at `09724ae` passed on 2026-10-15: `fitcheck-metrics-worker:20261015`, digest `sha256:774fddb5e8abb130ebad5a0be9ba6dbdd7d25c0966c579ff0075530e86f61af9`. This and the API image predate the whole-branch corrections; both need rebuilding. |
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
2. Apply additive **0004_metrics + 0005_metrics_erasure + 0006_metrics_coverage**, preserving frozen
   `0001`–`0005`. Verify runner code and actual packaged migration paths. The old
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
   select test scope. Supported staging: temporarily set website and collector to
   `test`, with API auth disabled and jobs disabled. AuthRuntime is then absent, so
   backend account product routes return 503; the independent MetricsRuntime can
   ingest the synthetic test observations without emitting backend domain facts.
   Keep `FITCHECK_METRICS_DATABASE_ENVIRONMENT=development` throughout. Rebuild/deploy
   website, submit a named non-PII event twice and confirm one stored fact plus
   duplicate behavior via operator report/aggregate inspection. This arrangement
   has been inspected locally; no remote staging settings have been applied yet.
   No new public test endpoint or configuration flag is introduced.
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
   companion OpenAI plan afterward, using next-free `0007` if pricing needs schema.

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

## Whole-branch correction qualification — 2026-10-15

The single correction wave adds 0006 coverage metadata and corrects recovered/as-of
job pending state. Existing image and schema evidence above predates this wave.
Deployment still has old 0003; no telemetry migrations were applied outside the
guarded disposable test database. Final tests, fresh 0005→0006 preservation/drift
checks and rebuilt API/worker images must be recorded before rollout. The next
OpenAI usage/pricing revision is 0007. Existing 0004/0005 migration files are frozen.

Backfill operators repeat bounded invocations until `backfill_complete` is true and
`backfill_complete_through` covers the report's exclusive end. A drain has a fixed
cutoff; outcomes beyond it require another drain. Partial coverage is explicitly
unavailable; insertion of an old fact cannot reverse the independent retention
floor. Mixed backend registration/outcome provenance is explicit in coverage.
Generic website failure causes and the success-publication rollback regression
remain nonblocking follow-ups. The unexplained transient lease test record above
is preserved without claiming a diagnosis.

## Actual rollout evidence — 2026-10-15 (in progress)

This section supersedes earlier pending statements only for the checks explicitly
listed here. Ingestion, erasure, final development configuration and restoration
of autodeploy remain acceptance gates.

- Final correction `e2a7eae8b5362db2731b9859490d42181985651f` passed the full backend
  suite: **669 passed, 1 skipped in 25.31s**. The single scoped rereview approved
  both Important findings with no new Important/Critical issue. Local API image:
  `sha256:4638d1ca9a63336ea9bb4bcb475e0f4f79b5bec2acb032a25f9830e40119e6e1`;
  worker: `sha256:a75ecaab1157076f1053e422d39d17db048fa9fb04e97ad588b26e2971b17605`.
  Packaged API CLI imports and reports head 0006 in a read-only, network-free container.
- All three autodeploy switches were verified OFF before pushing. CI passed at
  the exact correction commit: [run 38776070228](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/38776070228).
- The old live API reported head 0003 and no queued/running jobs. A temporary copy
  of its packaged migration directory received the exact hash-checked committed
  0004–0006 files. The existing migration connection/advisory-lock runner applied
  them and visibly reported `MIGRATED 0003 -> 0006`. The identical adapter had first
  passed a transactionally rolled-back disposable-schema test, preserving owner,
  job and provider-call data and proving repeated invocation a no-op.
- API Docker build completed remotely with image
  `sha256:644b2dbba09355eb169ab9f7a87e4716a0a79259f8ed616b0649c55bcef550aa`.
  External readiness returned HTTP 200 after the transient old-schema/new-schema
  gap. API container `2cd0390d57c1` later confirmed head 0006, collector `test`,
  independent database scope `development`, metrics enabled, auth/jobs disabled
  and ingest credential present (boolean only). Readiness then returned
  `{"status":"ok","stage":"foundation"}`.
- Running API and worker (`dc16e0c60304`) each had exactly 115 packaged Python
  source files with aggregate SHA-256
  `c0018ab4fab3c0f7f1c4a84bfc324bb1421f41f200fe285b951dc5f6de7f35a2`, matching
  the reviewed backend source. Worker health marker verification returned true.
- User explicitly approved metrics secret transmission to the existing dev
  recipients. Original API/website environment text matched before editing;
  provider/origin settings were preserved. API and website test configurations
  were saved; values were hidden afterward. No OpenAI credential was transmitted.
- The first real bridge POST returned 403 before any named synthetic fact was
  accepted. Exact public HTTPS origin was already allowlisted. This exposed an
  internal Next URL/public Host mismatch at TLS termination. The narrow fix
  `d2fec41112ec0aeeb866d400fe3ce84b04ed280a` retains mandatory canonical,
  explicitly allowlisted Origin and checks the direct URL or exact public Host;
  forwarded headers do not grant authority. Regression RED: 2 failed/8 passed;
  GREEN: 10 passed, TypeScript/lint/diff clean, production build passed. Independent
  scoped review approved spec and quality. Runtime acceptance is still pending.

Additional execution rulings, in order:

16. Add nullable independent retention floor and fixed backfill completion watermark
    in additive 0006, preserving prior migration files — partial historical inserts
    cannot prove continuous coverage or undo cleanup — cost if wrong: additional
    maintenance metadata and conservative unavailable periods until a drain completes.
17. Permit exact same-backend-account outcomes across observed/reconstructed
    provenance, with explicit mixed coverage and source retention floors — cohorts
    spanning collection inception otherwise lose known outcomes — cost if wrong:
    additional provenance checks; website/account identities remain separate.
18. Treat the newly reproduced proxy 403 as Task 8 runtime acceptance failure,
    separate from the completed final-review correction wave — live bridge proof
    is required to finish the task — cost if wrong: one additional narrow review
    cycle; mandatory origin allowlisting and same-host checks remain enforced.

### Real bridge acceptance — 2026-10-16

The proxy correction passed [CI run 38783805404](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/38783805404)
at exact commit `d2fec41112ec0aeeb866d400fe3ce84b04ed280a` and was deployed to
website container `c04a9d0e891f`. Both site and collector reported test scope;
database scope remained development. No model calls were made.

Container DNS resolved the API's public IPv4 address in 38 ms, but ordinary HTTPS
to that address timed out at 10 seconds, including with IPv4-first resolution.
The same public HTTPS hostname/SNI with normal certificate verification and
lookup directed to the container's observed default gateway returned HTTP 200 in
38 ms. A single container-local `/etc/hosts` mapping for
`dev-fitcheck-api.dokploy.gcexp.ru` corrected this hairpin route. Other hosts and
TLS verification were unchanged.

Two identical synthetic `page_viewed` submissions through the public website each
returned HTTP 202 with `delivered: true`. Aggregate database inspection found
exactly one named event, solely in test scope. The operator report, bounded from
the actual collection start, showed acquisition/direct/visitors = **1**, available.
A preceding one-hour query correctly reported unavailable precollection coverage;
the seven-day funnel had no mature cohort and a null ratio.

The public website DELETE for that disposable visitor returned HTTP 202 with
`delivered: true` and a rotated cookie. A follow-up database query found **zero**
remaining named events. No development data was reset or deleted; no broad cleanup
command or unscoped SQL deletion was used.

API auth/jobs were restored and external readiness returned HTTP 200,
`auth_storage`, database ready. Worker development metrics configuration was
saved and reloaded. Website development configuration was saved with a startup
prefix to make the tested host mapping survive container replacement, followed
by its unchanged `pnpm run start`. Final replacement-container verification is
still pending.

19. Persist the one-host gateway route in the website's Nixpacks startup before
    the original command — public-IP hairpin HTTPS timed out but the verified
    gateway route delivered real events — cost if wrong: this deployment requires
    Linux, a writable container hosts file and the host gateway's HTTPS listener;
    future nonroot/multinode deployments must revalidate or replace this routing.
    Rollback restores the original `NIXPACKS_START_CMD=pnpm run start` and redeploys.
    The prefix derives the gateway from `/proc/net/route`, validates IPv4, refuses
    conflicting existing hostname entries and only appends an absent entry. It
    contains no credentials and does not change certificates, hostname or ports.

### Persistent startup correction — 2026-10-16

The inline startup experiment built but replacement containers exited with status
0 and the site returned 502. The exact command-parsing cause was not established.
Restoring the original start command and rebuilding restored HTTP 200. This
supersedes the preceding pending inline-prefix configuration.

Commit `12c99c574e2521b15c3bcaf2ad709946e1ed852b` replaces inline code with
`ops/dokploy-website-start.sh` and an explicitly enabled gateway helper. Six
fixture/integration tests passed, covering route/hosts validation and startup
ordering, exec PID, exit propagation and helper-failure behavior. Independent
spec/quality review approved the patch with no Important/Critical findings.
The saved dev settings are `NIXPACKS_START_CMD=sh ops/dokploy-website-start.sh`
and `FITCHECK_DOKPLOY_METRICS_GATEWAY=true`; other environment entries are
preserved. CI and live replacement-container acceptance remain pending.

[CI run 38895425350](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/38895425350)
completed successfully for the exact startup-script commit; manual website
deployment was accepted. External API checks: readiness 200; unauthenticated
POST `/internal/metrics/events` 401; GET `/internal/metrics/report` 404;
unauthenticated GET `/v1/jobs/00000000-0000-0000-0000-000000000000` 401.
The report remains an operator CLI, with no registered public read route.

Replacement container `1103d3832668` stayed running. Its gateway flag was true,
both installed startup scripts matched local SHA-256, and its automatic hosts
entry pointed the single API hostname to `172.18.0.1`. No manual host edit was
made to this container. Normal HTTPS fetch returned readiness 200 in 56 ms;
website scope was development and both metrics secrets were present (boolean
checks only).

The subsequent real Chrome visit exposed `TypeError: Illegal invocation` at the
metrics client default `setInterval` invocation. The page entered its client error
fallback, so real development observation acceptance is still incomplete. A
receiver-preserving timer correction and focused regression/review are underway.

20. Correct the native timer receiver as a new Task 8 live acceptance failure —
    Node fake timers did not establish Chrome startup — cost if wrong: another
    focused implementation/review/deploy; injected timer contracts stay supported.

The receiver correction is commit `868d3b7b488dd5c76ebaf6f06b95be3b96bc6166`.
A receiver-sensitive regression reproduced the failure before the change. All
four default native timer functions now bind `globalThis`; injected timers keep
their receiver. The final focused run passed 25 tests, TypeScript and scoped
ESLint; independent spec/quality review approved with no Important/Critical
findings. Runtime acceptance awaits its CI and website deployment.

### Final metrics acceptance — 2026-10-16

[CI run 38896482162](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/38896482162)
passed at exact commit `868d3b7b488dd5c76ebaf6f06b95be3b96bc6166`. Dokploy
website deployment completed; replacement container `377b0dcd8b20` was running.
The real Chrome page rendered the Russian landing and local-account form. One
ordinary visit, without registration or a model request, changed development
`website_client/page_viewed` count from **0 to 1**. The operator report bounded
from the actual development collection start returned acquisition/visitors
**1**, available. API remained schema **0006**, development collector/database
scope, metrics/auth/jobs enabled. Worker health and scope were already verified.

This completes metrics Tasks 1–8, including real test-scope delivery/deduplication,
scoped erasure, restricted collector access and actual development observation.
No paid model call or provider migration was performed. DeepSeek remains active
until the separate OpenAI migration plan completes its matched fleet rollout.
Autodeploy was held off during the controlled rollout and is restored after the
final documentation push; the following provider rollout must control it again.
