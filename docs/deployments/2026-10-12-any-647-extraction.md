# ANY-647: website vacancy extraction API

Implemented and pushed to `dev` on 2026-10-12, commit
`b31752fc897879db4cc2e2ee4affd81f6d809914`.

`POST /v1/extractions` now accepts URL or text and returns an editable vacancy.
The Python parser uses the existing Freelancer HTML fixtures and extracts title,
description, skills, hourly/fixed budgets, competition evidence and provenance.
The account must be verified; cookie mutations enforce Origin and CSRF checks.
Fetching validates public DNS/IP/redirect destinations, pins connections to the
validated IP, verifies TLS against the hostname and limits time, headers and body.
Failed fetches count against persistent account/IP rate limits. Safe error responses
suggest manual input. The response does not replace an existing draft automatically.

Validation on the final implementation:

- 394 backend tests passed, including PostgreSQL HTTP/storage integration tests.
- 298 frontend tests passed; three optional live tests skipped.
- TypeScript, ESLint, OpenAPI/generated TypeScript drift and diff checks passed.
- Independent review approved after adding regressions for daily/weekly/annual rates.

Dokploy application `fitcheck-api-dev` reports a completed deployment of the above
commit. No database migration or reset was needed: competition/provenance fields
are stored in the existing JSON payloads.

Post-deployment checks at `https://dev-fitcheck-api.dokploy.gcexp.ru`:

- `/health/ready` returned 200.
- Live OpenAPI contains the implemented extraction route with web-session security.
- An anonymous text extraction returned 401 / `unauthenticated`.

Authenticated success, editable draft round trips, safe network errors and limits
were verified against disposable PostgreSQL locally and in backend CI, rather than
creating test accounts in the deployed database.

The website continues using its existing extraction flow until ANY-653 connects the
backend adapter. Guest admission remains ANY-651. History/job execution are separate
tasks; the extraction URL is preserved as `vacancy.url`, following redirects as in
the previous website implementation.

CI completed successfully, including the production website build:
<https://github.com/NikitaPotapovIt/fitcheck/actions/runs/38279710957>.
