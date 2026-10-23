# ANY-736: guest demo observations

Status: approved; implemented and verified locally, deployment pending. Parent ANY-734; follows deployed ANY-735 (`9f2dca3`).

## Goal

Observe the guest demo path in RU/EN: vacancy input started, URL extraction
requested, analysis requested and result actually displayed. Preserve the
difference between an observed request attempt, an admitted/completed domain job
and an observed result view. Telemetry failures must not affect the demo.

## Current findings

`WebsiteApp` owns a metrics client and safe observation callback. `DemoAnalysis`
does not receive the callback. `VacancySource` already provides onInputStarted.
Server analysis admission/polling knows jobId and analysisId, but the returned
entry currently loses job context. The collector validates event shape and signed
visitor provenance through the relay, without checking guest/job/result ownership.
Backend account lifecycle deliberately excludes guest owners. Guest claim moves
jobs/results without changing their IDs.

## Recommended approach

Reuse the existing metrics client, relay, collector and journal. Extend the event
contract with explicit demo/account context and safe locale/inputMode dimensions.
Wire DemoAnalysis input/request callbacks and observe result presentation only
after the result view is committed to the UI. Do not use job success as a view.
Retain the existing account observations and avoid a second client/session/queue.

Carry the analysis request correlation through admission/polling and retain stable
job/result IDs for telemetry. Attempts rejected before admission remain observed
attempts; they must not become verified jobs. URL extraction is observed only
when invoked, not on text input or field changes.

The relay forwards only the current allowlisted guest session cookie to the
authenticated collector boundary. Backend code resolves the server session and
checks job/result ownership using existing domain rows. Neither browser-supplied
guestId nor possession of a result UUID establishes ownership. Add minimal
persisted, server-confirmed demo linkage alongside journal events as needed,
using an additive migration; preserve the original visitor population and times.
Keep this relation separate from visitor/account attribution in ANY-737.

Use existing job/domain facts for accepted/completed analyses rather than enabling
guest events as backend account lifecycle facts. Guest claim preserves the same
operation and result identifiers. Deletion/retention must remove dependent proof
rows without reviving erased visitor identities or leaking claimed guest data.

## Repeated views and delivery

Suppress re-renders and polling observations in the UI. Retries use the same event
ID and existing journal deduplication. Define a unique first observed view per
visitor/result, with subsequent deliberate reopen/reload observations classified
as repeat rather than another first activation. Persisted server classification
must handle concurrent tabs and must not trust a client claim of first view.
Do not emit a view for errors, quota denial, or a result that was never displayed.

## Alternatives

Client-only instrumentation is smaller but cannot substantiate guest ownership or
stable operation/result links and does not satisfy the issue. A separate demo
analytics pipeline or classifying guests as registered accounts would duplicate
collection and mix populations. The recommended extension preserves the existing
architecture and meets the ownership requirement.

## Verification and limits

Component tests cover RU/EN, text/URL, resume, failure/quota, repeated render,
polling and reopen behavior. PostgreSQL integration tests cover persistence,
transport retry, first-view classification, forged/foreign IDs, claim preservation,
visitor/account deletion and isolation. Use stubbed LLMs; no paid calls required.
Generate/check backend TypeScript contracts after contract changes and run the
relevant installed Next.js guide/checks before changing route code.

SMTP remains unconfigured in development by the user's choice. Do not add a
mailer, bypass verification or claim that live account/claim checks passed.
Exercise that path with existing capturing-mailer fixtures in disposable tests.
No funnel recalculation, cross-device identity linking, dashboard or durable
browser outbox is included. Preserve the separate uncommitted ANY-735 evidence.
