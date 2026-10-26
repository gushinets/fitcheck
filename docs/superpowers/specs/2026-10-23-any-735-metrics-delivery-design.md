# ANY-735: delivery verification and diagnostics

Status: approved by user; target environment is existing Dokploy development.

## Goal and boundaries

Prove browser → Next relay → collector → committed PostgreSQL journal delivery,
and server lifecycle persistence in the selected environment. Operators must be
able to distinguish disabled or misconfigured collection, rejected requests,
transport failures and confirmed delivery. Product operations continue during
telemetry failures. No persistent browser outbox, new analytics platform, demo
instrumentation, identity linking or funnel redesign is included.

## Verified current behavior

- Browser transport already requires `delivered === true`; HTTP 202 alone does
  not confirm delivery. The client retries three times and has bounded counters
  for failed and dropped observations, available only through its local instance.
- Bridge returns a boolean for configuration, HTTP and transport failures.
- Collector returns accepted/duplicate counts after leaving its unit of work.
  Existing PostgreSQL tests cover persistence and duplicate IDs.
- Private operations metrics expose general HTTP counters and database health,
  without a dedicated collection configuration/delivery breakdown.
- The current page calls `connection()`, so the old README assertion that its
  metrics props always require build-time configuration is stale.
- Remote deployment state has not been checked. Local dotenv values cannot
  establish server state.

## Approach

Recommended: extend existing private operations monitoring and safe structured
diagnostics; retain existing client/relay/collector contracts where possible.
Distinguish missing configuration, HTTP rejection, timeout/network failure and
successful delivery using bounded reason codes. Never log request bodies, raw
exceptions, credentials, visitor IDs or destination URLs containing secrets.
Expose enabled/configured state separately from evidence of committed events.
Document process-local counter reset and replica scope.

Client drops and exhausted retries remain a separate observation source. Provide
an operator-usable way to inspect bounded client counters, and explicitly state
that closing a page, blockers and a failed diagnostic transport can leave losses
unobserved. Do not report these counters as an exact global loss rate.

Configuration-only repair is insufficient because it leaves failures silent.
A new durable queue or telemetry service exceeds the issue scope.

## Verification and rollout evidence

Add focused regression checks for false delivery acknowledgements, disabled and
invalid configuration, collector rejection, outage, timeout, exhausted retries
and queue overflow. Run PostgreSQL integration checks against an explicitly
disposable `_test` database, verifying committed rows from another transaction
and one row after replay of an identical event ID. Use stubbed provider calls.

Provide a smoke procedure for the selected environment: record commit and UTC
time, website/API/worker/report configuration readiness without secret values,
control event IDs, SQL and observed source/environment/subject values. Verify a
non-paid browser action and server operation. Compare report coverage with the
observed collection start. Do not fabricate historical views or auto-backfill
facts that cannot be reconstructed. Remote evidence remains pending until run.

## Decisions still needed

User confirmed Dokploy development and approved implementation. Live patched
deployment and post-deployment acceptance remain pending.
