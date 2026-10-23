# ANY-735 delivery verification — development

Date: 2026-10-23. Target: existing Dokploy development. Local base: `d82b64d`;
changes described here are uncommitted and **not deployed**. This is evidence for
the existing runtime and local patch, not acceptance of the patched deployment.

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

## Remaining acceptance

Patched runtime deployment and post-deployment smoke remain pending. Record exact
deployed commits/images, repeat the real browser action, prove one non-paid backend
lifecycle action and worker publication, and compare report coverage with those
control rows. No production outage/configuration failure was induced in the used
development; those scenarios ran automatically in isolated tests instead.
No live backfill or historical view reconstruction was performed. A report with
unavailable rows is evidence of its ability to read and declare limitations, not
proof of all ANY-738 funnel formulas. Do not close ANY-735 as fully accepted yet.
