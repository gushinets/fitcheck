# ANY-737: confirmed visitor → guest → account links

Status: approved by user; implemented and locally verified; deployment pending. Parent ANY-734; follows deployed ANY-736
(`95ae2233a3dfe21758424ab861ed18de126a7b5a`, schema 0010).

## Purpose and scope

Persist evidence that the current browser visitor successfully registered,
signed in, or claimed a guest demo. Give later report calculations a separate,
explicit projection of confirmed transitions and attribution intervals. Preserve
visitor/account populations, original journal timestamps and domain job IDs.
No cross-device stitching, fingerprinting, new dashboard or funnel formulas.
No SMTP configuration or paid model calls. Preserve the separate uncommitted
ANY-736 deployment evidence.

## Existing behavior

The website signs an HttpOnly visitor cookie with METRICS_COOKIE_SECRET. The
backend relay currently forwards auth/guest cookies and strips other client
headers; it does not convey verified visitor context. Backend auth sessions
identify the account. ANY-736 stores server-verified visitor/guest observations
in metric_demo_links. Claim has a stable receipt and moves job/result ownership
without changing IDs. Existing login rotates the old session, logout revokes it,
and password reset also revokes sessions. Expired auth-session rows are pruned
by maintenance; analytics evidence must survive that shorter retention.

Registration commits account/session rows before calling the mailer. Mail sending
can subsequently fail. An account_registered domain fact therefore does not by
itself prove a successful registration response with visitor attribution.

## Approaches

Recommended: attest the existing visitor cookie at the Next relay and verify that
attestation in the existing backend auth/claim flow. Persist minimal transitions
and session bounds separately from the visitor journal. This reuses both trust
boundaries and needs no new secret or browser account-ID payload.

Client-only linkage cannot prove successful auth/claim and would permit forged
IDs. Sharing the cookie-signing secret with the backend would add configuration
and expose its signing authority to another runtime. A second asynchronous
identity collector would require new durable operation receipts to establish
which auth operation actually succeeded; the current flow already knows this.
The user approved this approach for implementation.

## Trusted context and successful transitions

- Next validates exactly one existing signed visitor cookie, including its
  original issuance and expiry. Missing, expired, erased or malformed cookies
  do not create a replacement identity for attribution.
- Relay creates a short-lived, domain-separated HMAC attestation with the existing
  metrics bridge key. It binds environment, visitor ID, cookie issuance, request method/path,
  server issuance/expiry and request correlation. Browser-supplied attestation
  headers are stripped; the backend verifies the signature and destination.
  The backend does not receive the cookie-signing secret or credentials in logs.
- Only successful register, login and claim operations may create transition
  evidence. Account/session/guest/receipt IDs come from verified domain state,
  never arbitrary JSON or browser headers. Invalid/missing analytics context
  must not reject an otherwise valid business operation.
- Registration linkage is attempted only after AuthService.register returns
  successfully, including mail delivery. The API then verifies the issued
  session and newly created account before persisting the transition. Mail
  failure can leave an existing account_registered fact, but must not add a
  successful visitor-registration transition.
- Login uses the newly issued, verified session and the distinct login reason.
  It never creates another account_registered fact or a registration transition.
- Successful claim verifies account and guest proofs plus the persisted claim
  receipt. These proofs establish the claim edge at claim time even when the
  browser demo observations have not arrived yet. Historical demo attribution
  additionally requires ANY-736 proof for that same visitor and guest; absent
  observations leave earlier coverage unknown. Late observations can join this
  persisted claim without replaying the business operation. Never attach other
  visitors' guest observations to the account.
- Persistence is idempotent by environment, transition kind and server session
  or claim receipt. A replay never rebinds that operation to another visitor.
  Erased visitors and deleted account/guest/session/receipt state cannot be
  resurrected by late delivery or replay.
- Analytics persistence is best effort around the already successful business
  result: fixed safe diagnostics and unknown coverage on failure, no auth/claim
  failure solely because analytics delivery/persistence failed.

## Temporal boundaries and shared-browser rules

Transitions establish evidence at their server-confirmed operation time. They do
not rewrite earlier visitor rows into account rows. A registration point may
support a conversion join to the preceding anonymous segment, separately from
account activity; ANY-738 chooses metric windows/formulas. That segment cannot
cross an earlier account's authenticated interval or logout/account switch.
Existing-account login never retrospectively claims anonymous activity.

An authenticated attribution interval starts at successful session issuance and
ends at the earliest of logout, revocation, expiry or a confirmed account switch.
Use half-open [start, end) intervals. Persist the session/operation IDs and
confirmed closure/expiry evidence so later pruning of auth-session rows does not
extend or erase those boundaries. Hook session revocation centrally and archive
its final bounds before maintenance removes the source row. Failed analytics
closure must not become an inferred open interval: readers use live session
state while available, and otherwise report unknown unless final bounds were
confirmed. Maintenance must preserve source evidence until it can archive it.

A missing/deleted visitor cookie has unknown attribution even if an account
session remains valid. A subsequent new visitor cookie does not inherit a prior
visitor's windows. Visitor rotation/erasure prevents stale queued observations
from rebuilding the deleted association.

Concurrent/overlapping sessions that cannot be uniquely assigned to one account
are unknown, not guessed from the last processed login. Read projections expose
ambiguity and coverage explicitly. Claim is a transition at claim time; earlier
guest events retain visitor/guest provenance and stable job/result IDs.

## Storage and read interface

Add an additive migration after 0010 with a minimal transition/interval schema:
environment, visitor ID, account owner FK, optional original guest owner FK,
reason (registered/login/claim), confirmed operation/receipt/session ID,
server operation time, cookie issuance, session expiry and confirmed end/basis.
Uniqueness keys deduplicate each domain transition. Owner/guest erasure removes
related identifiers and claim evidence; auth transitions become anonymous time
guards with no account, guest, source or session identifiers. Guards preserve
switch/overlap uncertainty until a later non-overlapping auth or their original
hard expiry; they are not returned as confirmed transitions. This deliberately
prefers unknown coverage over reassignment after erasure; visitor erasure explicitly deletes all links and anonymous guards and preserves
its existing opaque tombstone. Retain confirmed analytics evidence for at most
180 days through bounded maintenance, without retaining auth tokens or passwords.

Provide bounded read-only projection functions for transitions and unambiguous
account-at-time links, plus anonymous-segment/guest-claim provenance and unknown
coverage reasons. Keep them separate from existing event/operation populations.
ANY-738 can consume this projection; it does not alter report formulas here.
The exact table split and function signatures are implementation-plan choices.

## Verification

Use capturing-mailer and domain fixtures in disposable PostgreSQL. Test new
visitor/demo/register/claim, register without demo, mail/credential/claim failure,
receipt and delivery replay, login vs registration, logout/account switching,
concurrent ambiguity, forged/foreign IDs and attestation, absent/expired/duplicate
cookies, missing guest proof, account/visitor erasure and late retries, and
retention after auth-session pruning. Assert unchanged job/result IDs and original
visitor journal rows, no email/password/user texts in analytics/logs, and no
business failure when analytics is unavailable.

Relay tests prove signature generation, header stripping, route/time binding and
no invented visitor. Regenerate/check OpenAPI/TS only if public contracts change;
run frontend/backend regression suites, schema drift, lint/typecheck/build and a
fresh final review. Development smoke remains limited by the user's existing
choice to leave SMTP unconfigured; do not bypass verification to claim acceptance.

Builder check: fresh independent reviewer found nothing important left to answer
before planning. The author clarified that delayed demo observations can join a
confirmed claim edge without requiring another business claim. The user subsequently approved implementation.
