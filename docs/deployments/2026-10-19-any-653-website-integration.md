# ANY-653 — website and backend integration

The website now uses server account sessions, profiles/revisions, preferences,
drafts, extraction, durable analysis/suggestion jobs and server history. It reads
server result IDs and snapshots; it never writes a client-generated result into
server history. History supports application status, filtering, pagination and
reanalysis using the current server profile. Legacy records without profile
snapshots display without inventing a profile.

## Configuration and rollout

1. Deploy compatible API and worker with auth, jobs and guest features enabled.
   Configure SMTP and `FITCHECK_AUTH_WEB_BASE_URL` to the public website origin.
2. Set website server-only `FITCHECK_BACKEND_URL` to the API base origin (without
   `/v1`) and `FITCHECK_WEBSITE_ORIGIN` to the exact public website origin. Put that
   origin in backend `FITCHECK_ALLOWED_ORIGINS`. The relay fails closed when no
   backend is configured. No `NEXT_PUBLIC_*` variable or provider credential is
   used by the website adapter.
3. Serve HTTPS in production. Backend Secure HttpOnly `__Host-fitcheck_*` cookies
   are passed unchanged to the website origin. Development backend mode uses
   unprefixed cookies for local HTTP. Browser cookie/session/CSRF isolation is
   handled by the backend; the relay forwards only FitCheck auth/guest cookies,
   CSRF proofs, idempotency keys and JSON content type. It does not forward bearer
   tokens or service credentials. All relay responses use `no-store`.
4. Configure a trusted ingress chain separately before relying on per-IP quotas
   across many users. The relay does not trust client-supplied forwarding headers;
   without a trusted ingress integration the backend sees the relay's IP. Account
   and guest quotas still use their server owners.
5. Deploy the website. `/api/analyze`, `/api/extract` and `/api/skill-suggestions`
   return 410 for all callers. They cannot invoke a provider or bypass quotas.
   Provider keys belong on the worker; remove obsolete website provider settings.
6. Smoke-test verification/reset email links, demo/claim, import retry, reload of
   an in-flight analysis, history in another browser, and foreign-record denial.

## User behavior

Registration requires a 15–128 character password. Pending accounts receive an
email verification screen with resend and code entry. Email links use fragments
on `/auth/verify-email` and `/auth/password-reset`; token fragments are removed
from browser history when read. Account deletion asks for the current password.
Profile edits send `expectedRevision`; a conflict never silently overwrites
another device's work.

Guest demo uses a separate server session. Its CSRF proof stays in sessionStorage
through registration; a verified user explicitly claims it on the profile page.
Retries preserve the claim idempotency key. The legacy importer asks for the
previous local account credentials, exports only that account, and polls its
server import job. The import key is a hash of the bounded export; retrying the
same payload reuses the server receipt. Existing server data is preserved and
outcomes report imported/skipped/conflicting/invalid records. Local legacy data
is retained for recovery and is never treated as a server account session.

An in-flight analysis stores an owner-scoped admission key and draft/job reference
in localStorage; no password/session token is stored there. Reload recovers the
server session and resumes polling. A lost admission response reuses the same
key. Terminal failures release the pending record; polling timeouts preserve it.
Logout/deletion clears the current owner's pending record and in-memory views.

## Reproducible checks

Run `pnpm test`, `pnpm typecheck`, `pnpm lint`, `pnpm backend:types:check` and
`pnpm build:web`. If the local environment cannot run Turbopack's child-process
socket, `pnpm exec next build --webpack` verifies the production application.

Browser E2E uses real FastAPI auth, PostgreSQL ownership/queue/publication and a
deterministic test-only executor with captured mail. It never calls a paid model.
The fixture is loopback-only, lives under `e2e/`, and is absent from production
routes. It creates/resets only the dedicated database `fitcheck_e2e_test` and
refuses other database names or non-loopback hosts.

```sh
docker compose -f backend/compose.test.yaml up -d
# Install backend development dependencies in backend/.venv first.
pnpm exec playwright install chromium
pnpm exec next build --webpack
pnpm test:e2e
```

Default test PostgreSQL: `fitcheck_test:fitcheck_test@127.0.0.1:55464`.
Override `FITCHECK_E2E_DATABASE_URL` for another loopback test instance while
retaining the database name `fitcheck_e2e_test`. API port 38154 and website port
38153 must be free. Test mail and deterministic publication are never enabled
through production environment flags.

Production deployment and paid provider verification are separate from this
local implementation; ANY-654 covers deployment/monitoring/backup acceptance.

## Local validation — 19 October 2026

- Vitest: 410 passed; three existing opt-in live checks skipped.
- TypeScript, ESLint, generated backend contract drift and `git diff --check`: passed.
- Production build: passed with Webpack. Local Turbopack failed on its child
  process socket with `Operation not permitted`; no application compile failure
  remained in the Webpack build.
- Playwright Chromium: both scenarios passed against real FastAPI/PostgreSQL.
  The first covers demo, registration/verification/claim, analysis reload,
  history on a separate browser context, status updates and cross-owner 404.
  The second covers IndexedDB import, idempotent retry and opening an imported
  result without a historical profile snapshot.
- Browser chunks contain none of the checked provider-key/prompt markers.
- No production deployment or paid provider calls were made.
