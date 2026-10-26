# ANY-652: import local website data into a verified server account

Status: proposed written specification; conflict policy approved in conversation.

## Outcome and scope

Transfer the selected IndexedDB user's profile, locale and analysis history into
the currently authenticated, email-verified server account. Preserve local data,
historical inputs/results and repeatability. An existing server profile wins;
differences are reported rather than overwritten. This is the prerequisite for
ANY-653, which owns the website's server sign-in and migration screens.

ANY-652 includes a safe client export function, authenticated import endpoints,
durable worker execution, reports and tests. It does not switch WebsiteRepository
to server storage, delete IndexedDB, migrate passwords, run LLM calls or solve
the separate Dokploy webhook certificate issue. Draft migration is outside this
ticket's profile/history scope; existing local drafts remain untouched.

## Existing boundaries and chosen approach

`lib/web/repository.ts` stores users, profiles, preferences, drafts and history in
IndexedDB version1. `loadSnapshot()` returns only the newest50 history rows, so
export must query the selected user's history directly, without that display
limit. Local history already carries a profile copy, but does not establish a
server profile revision, prompt version or historical locale.

The backend already declares POST `/v1/import-jobs` and GET
`/v1/import-jobs/{importId}`, an import job type and owner-scoped ImportEntry
deduplication. These are scaffolding, not a complete importer. Current analysis
serialization requires server snapshot metadata and must be extended explicitly
for imported history; making up a server revision is unacceptable.

Use the existing durable job queue with per-record transactions and receipts.
A synchronous whole-upload transaction would simplify atomicity but makes
partial recovery and large histories harder. Client-orchestrated one-request-per-
row import would push correctness into browser lifetime. The durable job keeps
progress authoritative on the server and reuses existing worker recovery.

## Client export and format

Add an explicit readonly export operation for the active selected local user.
Read active session, selected user, profile, preferences and all matching history
in one IndexedDB transaction. Require the requested selected user to match that
session. Reject stale selection rather than exporting a different user. Filter
every history row by owner; never enumerate other users into the export.

Construct the export with an allowlist. No password digest, salt, email,
authentication/session object or provider operation credential is included.
Do not use object spreading from stored users or arbitrary stored records.
The local user ID is a source identifier only and grants no server authority.

Format version1 contains source=`website_indexeddb_v1`, sourceUserId, optional
profile, optional locale and a history array. Each row has its external local ID,
createdAt, job, result, optional historical profile and optional feedback.
Preserve source URL, currency, skill levels, evidence and original timestamps.
Legacy monthly income is discarded; missing skill levels/currency use the
existing documented profile normalization. Missing URL is valid. Do not infer
historical locale from today's preference; represent unknown locale as null.

Maximum1000 rows and at most the configured HTTP body limit, with a hard import
ceiling of5MiB. The effective limit is the smaller limit. Exports exceeding either
limit fail explicitly without truncation. The client can submit disjoint batches
under the same source identity; receipts deduplicate across batches. Each row
retains existing domain string/list bounds. Reject unsupported envelope versions
and duplicate external IDs within one request before creating a job. Invalid
individual records receive stable row errors and do not block valid siblings.

The declared but unimplemented legacy request shape is updated to match this
real source format; regenerate OpenAPI and TypeScript together. No deployed
successful importer exists whose older wire behavior must be preserved.

## Authentication and admission

Require an active verified server account, allowed Origin, account CSRF proof
and Idempotency-Key for admission. Guest identity and matching local email are
insufficient. Derive target owner exclusively from the server session. Polling
requires the same owner and active verified session; foreign import IDs return404.

Use existing owner locking and account active-job ceiling for import admission;
do not charge analysis credits or allocate LLM budget. Bound retries using the
existing queue policy. A disabled jobs gate also disables new import admission.
Revalidate owner/account existence before each worker transaction. An admitted
job may finish after logout, as other durable jobs do; account erasure must
prevent later publication and remove its payloads/receipts.

Same owner/key/canonical payload returns the original import reference. A reused
key with different content returns409. Persist validated bounded input and report
only; never log uploaded bodies or raw rejected values.

## Profile and preference conflict rules

Lock the owner before checking and changing profile/preferences. If no server
profile exists, import a valid profile through the profile service invariants as
the first real server revision. If profiles match after normalization, report
skipped. Otherwise preserve the server profile and report a conflict. Historical
profile snapshots do not become fake server revisions, even if identical.

Copy locale only when no stored server preference exists. Equal values are
skipped; differing values are conflicts and preserve the server value. Historical
rows still import when the current profile or preference conflicts. Invalid
optional profile data is reported without discarding valid history.

## Historical record representation

Persist imported analyses and vacancies using existing owner-scoped tables,
with no analysis worker job, no provider call and no fabricated execution data.
Keep original createdAt and feedback createdAt. Validate aware timestamps and
store instants in UTC. Present missing feedback and URL as absent, not defaults
that imply they existed.

Extend snapshot decoding/OpenAPI with a discriminated legacy representation.
Existing native/guest snapshots remain wire-compatible. Legacy snapshots identify
their import origin, carry vacancy and the historical profile when present,
nullable locale, and null profileRevision/promptVersion/policyVersion. An explicit
legacy snapshot schema version is truthful format metadata. Missing historical
profile stays null; never fill it from today's selected profile. Server-generated
profile comparison remains unknown for imported history. Recalculation of legacy
rows requires a real current account profile and creates a new normal job.

Imported strength evidence is retained as unverified legacy evidence, never
presented as proof of a server-verified execution. Validate result fields without
recomputing score, verdict or evidence. No LLM repair is attempted for old data.
Unreadable rows are skipped with a typed reason and their external ID only.

## Deduplication, progress and recovery

Extend import receipts to scope uniqueness by target owner, source format,
sourceUserId and external ID. Store the canonical hash of normalized source data
alongside the imported analysis reference. Source identity separates independent
local users while remaining untrusted input. Two browser exports of identical
source rows deduplicate within the same server account.

For each valid row, lock owner, check receipt, then atomically write vacancy,
analysis, annotation, receipt and progress. An identical hash means skipped;
a changed hash means conflict, preserving the prior imported/server record.
Never silently overwrite later feedback or status edits on retry. The receipt
and data must commit together. Profile/preference processing likewise records a
durable outcome, so retries cannot reinterpret their own previous writes.

Persist per-item outcomes and stable counters: importedCount, skippedCount,
conflictCount and invalidCount, plus separate profile/preference outcomes.
Expose progress and a bounded list of row outcomes through GET import state.
Counter meanings exclude profile/preferences and sum to the submitted row count
when complete. Reports contain IDs and typed reason codes, not uploaded content.

Use the current worker lease token as a fencing condition on every progress/data
transaction. Recovery skips completed items and continues the remainder. A
transient failure leaves committed items intact; the same-key polling/retry
recovers the same job. After terminal exhaustion, a new idempotency key may
resubmit the unchanged batch; global receipts prevent duplicates. Invalid rows
and content conflicts complete with a report rather than failing the entire job.

Deleting server history also deletes its import receipts, consistent with the
current schema: an explicit subsequent import may restore deleted history.
Document this behavior instead of promising permanent deduplication after erase.
Local data is never deleted automatically, including after successful completion.

## Persistence, compatibility and operations

Add migration0009 for source identity, durable import item outcomes/progress and
necessary constraints. Preserve existing rows and inspect scaffold constraints
before replacing them. Imported snapshots must be supported by every history,
recalculation and serialization path. Keep native/guest job envelopes unchanged.

Deploy matching API and worker with the existing schema-safe procedure: pause
admission, inspect/drain jobs, apply additive migration, deploy both images,
verify schema/health, then resume admission. Do not downgrade the database to
restart an older image or remove imported user data as rollback.

## Acceptance and validation

Client tests use real fake-indexeddb transactions: two users, selection change,
more than50 rows, old profile schemas, no URL, allowlisted export with no digest
or session, deterministic batching and local data retained after success/failure.

Backend HTTP tests cover verification/auth/Origin/CSRF, size/version limits,
owner isolation, same-key replay/conflict, per-row errors and report contracts.
PostgreSQL integration tests cover concurrent admission/import of the same rows,
profile races, source users sharing row IDs, partial commit/crash/recovery,
expired lease fencing, changed source content, annotation preservation, erasure
and old snapshots without revision/profile/locale. No paid provider is used.

Run the full backend suite, relevant client tests, generated contract drift,
TypeScript/lint/build checks and both Docker image checks before completion.
If implementation touches Next.js, read its installed relevant guides first as
required by AGENTS.md. ANY-653 owns the eventual browser migration wizard/E2E.

## Review record

Self-review: scope excludes website integration and credential migration; every
accepted row has a durable outcome; retries cannot duplicate publication;
conflicts preserve server data; historical unknowns remain explicit. No product
code or migrations have been changed at this specification stage.
