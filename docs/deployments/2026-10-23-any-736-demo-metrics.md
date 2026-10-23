# ANY-736 — implementation and verification

Status: implemented locally; not deployed by the agent.
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

Live development smoke remains pending deployment: verify a real demo's safe
input/request events, then view/reload classification and one admitted job.
Use a provider stub for job completion if available; this implementation has not
made a paid live analysis or claimed a live email-verified account check.
