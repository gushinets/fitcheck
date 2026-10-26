# ANY-735 delivery verification — development

Date: 2026-10-23. Target: existing Dokploy development. Implementation commit:
`9f2dca3855053fec2b8e2753181111f165e04580` (base `d82b64d`). The user deployed it;
post-deployment checks follow below. Earlier observations describe the previous runtime.

## Live observations

Via existing authenticated Dokploy UI terminals; no settings, secrets, migrations,
deployments, domain records or provider calls were changed. One named synthetic
visitor observation was delivered and replayed. Do not treat it as organic demand.

| Component | Observation |
| --- | --- |
| Website container | `b9fdeef14f15`, running; process environment audited at `2026-10-23T16:16:50.315Z` |
| Website configuration | URL/key/cookie secret/origins nonempty, metrics environment development, collector HTTPS |
| API container | `b75f5a53795a`, running; enabled/configured true, environment and independent database scope development |
| Worker container | `4279d5c1bdd3`, running; enabled/development/database-scope-development/heartbeat all true |
| Database schema | `0009` |
| Relay control | event `73500000-0000-4000-8000-000000000003`, `history_viewed`, occurred `2026-10-23T16:18:23.397Z` |
| Relay result | two POSTs, preserving cookie and payload: HTTP 202, delivered true both times |
| Independent DB read | one committed row, source website_client, environment development, subject_kind visitor, received `2026-10-23T16:18:23.441684Z` |
| Journal source summary | website_client 58 rows; website_server 3 rows (last received 2026-10-17). No backend_server rows in the inspected summary; this does not prove disabled lifecycle collection |
| Existing CLI report | exit 0; `[2026-10-23T16:18:00Z, 2026-10-23T16:19:00Z)`, development/all, Europe/Moscow; 205 rows, 108 unavailable |

The replay control was sent from the website container through the actual Next relay.
A separate ordinary Firefox page load was subsequently verified in PostgreSQL: event
`e3865b79-2419-4686-894c-719b85629eca`, page_viewed, website_client/development/visitor,
occurred `2026-10-23T16:25:57.062Z`, received `2026-10-23T16:25:57.143581Z`.
The independent worker-container DB read ran at `2026-10-23T16:26:38.415439Z`. Node fetch to local ingress returned 403; explicit node:http with
public Host and exact configured Origin succeeded. Public HTTPS loopback from
inside that container failed. These probes do not establish browser failure or a
public ingress defect. The later browser check passed through public ingress; those container probes did
not reproduce its network path.
Failed probe UUIDs ended in `...000001` and `...000002`; successful control is `...000003`.

The API terminal must use `/app/.venv/bin/python`; system Python has no SQLAlchemy.
The independent read used a new engine/connection, a read-only transaction and
3-second statement timeout. No visitor IDs, cookie values, user texts or provider
credentials are included in this record.

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '3s';
SELECT version_num FROM alembic_version;
SELECT event_id, name, source, environment, subject_kind, occurred_at, received_at
FROM metric_journal
WHERE event_id = '73500000-0000-4000-8000-000000000003';
SELECT count(*) FROM metric_journal
WHERE event_id = '73500000-0000-4000-8000-000000000003';
SELECT source, environment, count(*), max(received_at)
FROM metric_journal GROUP BY source, environment;
COMMIT;
```

## Local verification

- New bridge/client failures reproduced before implementation; focused diagnostics
  tests then passed. Review corrections also reproduced missing receipt validation
  and lost Prometheus outage samples before their fixes.
- Full frontend: 505 passed, 3 optional live tests skipped.
- Full backend with guarded disposable `fitcheck_test`: 1002 passed, 5 skipped;
  one existing dependency warning about Pydantic TypedDict ReadOnly behavior.
- TypeScript, focused ESLint, production Next build and diff whitespace checks passed.
- Independent review: two important findings fixed (strict collector receipt,
  scrapeable outage diagnostics plus matching database alert). Minor deferred:
  DELETE rejected by the outer body boundary before routing is in general HTTP
  counters but not the dedicated delete counter.

## Acceptance scope

The implementation is deployed and the account-free post-deployment smoke passed
(see below). The user explicitly requested proceeding without SMTP or a mail stub.
Live account registration/profile lifecycle and worker job publication therefore
remain unverified; their isolated integration checks passed during implementation.
Do not describe these live paths as accepted or close every original criterion
solely on the basis of this reduced smoke. No live outage was induced, no provider
call was made, and no backfill or historical view reconstruction was performed.

## Post-deployment checks

User reported deployment. Dokploy deployment lists for API and website both show
**Done** for `9f2dca3855053fec2b8e2753181111f165e04580` / ANY-735.

- API container: `589f6e22bc18`, running.
- Website container: `18b7493a0376`, running.
- API private exporter, using the existing configured ops token: HTTP 200,
  `fitcheck_database_up=1`, enabled/collector-configured/lifecycle-configured/
  database-scope-configured all 1. No token value was printed.
- New journal diagnostics were present: website_client observed=1/count=61,
  website_server observed=1/count=3; backend_server and reconstructed_backend
  observed=0/count=0. These are retained rows, not proof of zero real activity.
- A fresh browser page load displayed the normal registration page. A test-account
  session is needed for a real non-paid backend lifecycle operation; the user was
  asked to sign in and save a profile without launching an analysis.

Post-deployment replay, independent database read, worker readiness and CLI checks
completed successfully; details follow.


### Registration blocker found during acceptance

The user could not create a test account. Investigation of the deployed API
confirmed `auth_enabled=true`, `SMTPMailer(settings).available()=false`, and all
six SMTP fields absent (host, port, username, password, from, security), while
`auth_web_base_url` is set. Bootstrap GET returns HTTP 200 with a CSRF value both
through the website relay and directly to the configured backend (the CSRF value
was not printed). This isolates the observed configuration blocker from relay
connectivity and bootstrap authorization.

`AuthService.register` explicitly stops with `email_unavailable` before creating
a user when the mailer is unavailable. The UI has no specific translation for that
code and displays a generic request failure. No password, email, SMTP credential
or registration request body was read or logged for this investigation. No email
was sent by these diagnostic probes. Configure the existing SMTP fields in the
API deployment before attempting the account lifecycle acceptance step again.
This is an external environment prerequisite, not evidence of a telemetry defect.


### Completed checks without mail/account creation

At the user’s explicit request, no SMTP service or stub was added and no account
verification was bypassed. API, website and worker Dokploy deployment lists show
Done for `9f2dca3855053fec2b8e2753181111f165e04580`.

| Check | Actual result |
| --- | --- |
| Deployed worker | `c4996fb39b5a`, running; metrics enabled, development environment, independent database scope development, healthy heartbeat |
| Control event | `73500000-0000-4000-8000-000000000005`, history_viewed, occurred `2026-10-23T16:44:39.749Z` |
| Actual website relay | two identical POSTs preserving the signed visitor cookie; HTTP 202 and delivered true on both |
| Independent worker-container SQL transaction | exactly one row after replay, website_client/development/visitor; received `2026-10-23T16:44:39.815383Z` |
| Real browser event after deployment | page_viewed `43d973de-fc5d-4595-a8d3-a8770c5b0478`, website_client/development/visitor, occurred `2026-10-23T16:37:43.331Z`, received `2026-10-23T16:37:43.409540Z` |
| Live schema | 0009 |
| Existing CLI JSON and CSV | both exit 0, 100 metric rows each, development/visitor, period `[2026-10-23T16:44:00Z, 2026-10-23T16:45:00Z)` |
| Control report row | feature_adoption/history, website_observed visitor: available true, numerator 1, denominator 1, value 100 in both formats |
| Report coverage | data_start `2026-10-16T11:55:06.881Z`; explicitly observed-only, client blockers/failed delivery not exhaustively measurable |

The history figure describes the named synthetic control, not organic engagement.
It demonstrates delivery/replay/CLI consistency and does not accept the unrelated
funnel formulas in ANY-738. The new private exporter was already verified on the
deployed API: HTTP 200, database_up=1 and all four configuration gauges=1.

Reproduction SQL uses the read-only transaction above with control UUID ending
`...000005`. The real-browser lookup selects only event ID, event name, source,
environment, subject kind and timestamps; it does not expose visitor identity.
CLI invocation (from the deployed worker, using packaged Python):

```sh
/app/.venv/bin/python -m fitcheck_backend.metrics report \
  --start 2026-10-23T16:44:00+00:00 --end 2026-10-23T16:45:00+00:00 \
  --environment development --population visitor --format json
# Repeat the same command with --format csv.
```

No product code, deployment settings or secrets were modified during this final
smoke. Only this evidence document was updated locally. The deferred pre-routing
DELETE counter limitation and unverified live account lifecycle remain explicit.
