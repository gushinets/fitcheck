# ANY-736 — implementation and verification

Status: deployed by the user; basic development smoke verified by the agent.
Parent ANY-734. Depends on deployed ANY-735 (`9f2dca3`).

## Behavior

Demo RU/EN now uses WebsiteApp's existing metrics client/session/queue for
`vacancy_input_started`, `extraction_requested`, `analysis_requested` and
`analysis_result_viewed`. Safe dimensions are flow, locale and inputMode.
RequestId is the original admission idempotency UUID; rejected attempts do not
become admitted jobs. Views carry the stable jobId as operationId and the actual
analysisId as resultId. The view effect runs after presentation, suppresses
rerenders/polling, and does not run for unmounted results or failures/quota denial.

The relay forwards only one unambiguous guest cookie for demo batches. No account
cookie or browser-supplied guest ID is forwarded. Backend resolves that cookie,
then rechecks guest identity and job/result/session ownership in its transaction.
The journal remains visitor observations; new `metric_demo_links` rows contain
verified guest context. Foreign/missing/revoked proofs cannot establish a link.
First observed view is serialized per environment/visitor/result and persisted;
subsequent reopen events are repeat views. Delivery replay retains event IDs and
uses the existing journal deduplication.

A completed guest job's ID is retained in sessionStorage to reopen the demo after
reload without another admission. A different guest session or completed claim
clears that receipt. No profile/vacancy/result content is added to telemetry or
this receipt.

For ANY-738: `request_id` is correlation only, including before admission. The
corresponding authoritative job has the same `idempotency_key` and guest origin
in its frozen input (`mode=guest`, original `sessionId`). After claim, job/result
IDs and origin remain stable while current owner changes. `job_id`/`result_id` in
view proofs are verified, retained UUIDs, deliberately not foreign keys to
shorter-lived job rows. No guest is recorded as a registered backend account.
ANY-737 owns visitor/account attribution; this change does not recalculate funnels.

## Verification

- Frontend full suite: 519 passed, 3 skipped (52 test files passed, 2 skipped).
- Backend full suite including disposable PostgreSQL: 1008 passed, 5 skipped;
  one existing SDK/Pydantic ReadOnly warning.
- Final focused PostgreSQL guest metrics suite, including the subsequently added
  retention test: 7 passed. Covers owned/foreign IDs, stale sessions, delivery
  replay, concurrent first views, pre-admission attempt, claim, account/visitor
  deletion, no late visitor revival, and cascading metric retention.
- TypeScript, full ESLint, production Next webpack build and git diff --check
  passed. Generated OpenAPI and backend TypeScript artifacts are current.
- Fresh independent code review: no concrete defects found. Reviewer did not
  repeat full suites or assess live deployment or the deferred reports/attribution.
- Tests use existing capturing-mailer fixtures and domain stubs. No paid model
  calls, SMTP configuration changes or verification bypasses.

## Deployment

Deploy the changes to development using the existing pipeline. Run the standard
backend migration step to head `0010` before starting the new API/worker; the
migration adds only the demo proof table and indexes. Rebuild/restart website,
API and worker from the same revision. No new environment variables are needed.

Basic live development smoke is recorded below. A complete live analysis,
view/reload classification and account claim remain untested. Use a provider
stub for any additional job-completion smoke; no paid live analysis or live
email-verified account check is claimed.


## Post-deployment development smoke — 2026-10-23

User reported successful migration/deployment. Dokploy lists website, API and
worker deployments as Done on the same commit
`95ae2233a3dfe21758424ab861ed18de126a7b5a` (ANY-736).

- API container `56b553500138`: database schema `0010`,
  `metric_demo_links` exists; internal `/health/ready` returned 200;
  metrics enabled with environment development.
- Worker container `e7ee1a30cf4d`: packaged migration head `0010`;
  `python -m fitcheck_backend.worker.health` exited 0.
- Opened the deployed website in the real Firefox browser, entered RU guest
  demo without registration and filled a synthetic React profile manually.
  No skill-generation action was used.
- Filled a synthetic text vacancy, opened review and returned to source.
  Then loaded the public example.com page through URL extraction; the review
  displayed Example Domain. No analysis button was pressed.
- A separate SQLAlchemy read in the deployed API container confirmed the
  following committed visitor observations after smoke start
  `2026-10-23T17:25:25.652604Z`, each with a server-verified demo link:

  | Event | Input mode | Locale | Guest proof |
  | --- | --- | --- | --- |
  | vacancy_input_started | text | ru | present |
  | vacancy_input_started | url | ru | present |
  | extraction_requested | url | ru | present |

- New Job rows and ProviderCall rows since smoke start were both zero. This
  confirms that this smoke did not admit an analysis or make a model call.
- Closed diagnostic terminals and returned the demo to the account entry screen.
  No deployment settings, credentials or database rows were edited directly.

Limits: live `analysis_requested`, result view/reload/first-view classification
and account claim were not exercised; they remain covered by the local stubbed
component and PostgreSQL tests above. No SMTP setup or paid-provider validation
was performed. The observed live delivery/ownership result is limited to input
and extraction events, not an end-to-end completed analysis.
