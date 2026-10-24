# ANY-735 / ANY-738 — collection interruptions (F01)

Addresses review comments `428b6b71-ea0a-4132-9a1b-a38216389a13`
and `6707d1a9-cadb-4c3e-a95c-e1df6eee80a3`.
Local changes; no commit, push or deployment performed by the agent.

## Behavior

Backend collection coverage now includes known interruption intervals in addition
to the original collection/retention boundary. An API or worker runtime with
backend collection disabled opens its own identity-free interval, scoped to the
configured metrics environment (or configured database environment when the
emission environment is absent). Effective collection requires both the enabled
flag and an emission environment. Without either configured scope the runtime
cannot safely assign a marker to an environment.

Graceful shutdown closes only that runtime's interval. A new enabled runtime or
new event does not close another writer's interval or erase historical gaps.
Multiple disabled writers remain independent. Reports overlapping an interruption
return `available=false`, null value and a concrete reason; coverage includes up
to ten overlapping intervals, their total count and `incomplete_collection`.
Fully covered periods without actions can still report an available zero.
JSON and CSV carry the same availability, reasons and coverage.

Business registration remains successful while telemetry is disabled. Marker
storage errors are safely logged as `metrics_coverage_marker_failed` and do not
block business startup. As an independent safeguard, reports compare surviving
domain registrations with committed backend registration facts in the same
period/database scope. Missing facts mark the registration count unavailable and
expose the aggregate `missing_domain_registration_facts`; they never create
synthetic events or registrations. Existing result-view and feedback proof rules
are unchanged.

Closed interruption records expire after 180 days using the existing shared
maintenance batch ceiling. Their deletion advances the source retention floor,
so deleting evidence never relabels old unknown history as complete. Markers
contain no user identity or payload and survive individual user erasure.

## Limits and operational decision

An abandoned runtime with no recorded shutdown leaves an open interval. It stays
conservatively unknown even after enabled collection resumes: another process
cannot prove the disabled writer stopped. This may keep later reports unavailable
after a crash. Do not delete/close such a marker merely to obtain a numeric report;
any manual repair requires evidence of the actual stop time. No automatic repair
or destructive development cleanup was performed.

The migration does not reconstruct pre-patch interruptions or claim they are
known. A failed marker write cannot establish an interval; the registration
domain check detects surviving missing registration facts but cannot reconstruct
all omitted activity or erased history. Deployment health alone is not end-to-end
report acceptance. Existing SMTP/live-registration limitations still apply.

## Validation

The original F01 was reproduced on disposable PostgreSQL: one successful domain
registration, zero journal registrations, incorrectly available zero. The fixed
real-AuthRuntime control reports incomplete collection instead. Additional
controls cover all-period disable without actions, an internal gap, resumption,
covered zero before/after the gap, overlapping/abandoned writers, environment and
source isolation, storage failure without blocking registration, worker lifecycle,
JSON/CSV through the current CLI, bounded retention and retention-floor safety.

An independent final review identified enabled-without-environment as another
effective disablement path. Its real-runtime regression failed before the fix;
the predicate now matches the emitters.

Final full backend/PostgreSQL suite: **1088 passed, 5 skipped**, one preexisting
SDK/Pydantic warning (88.12 seconds). Includes fresh migration roundtrip and
schema-drift checks, the ten new coverage controls, and all previous result-proof,
session, erasure and accounting regressions. OpenAPI and generated TypeScript
artifacts are current; `git diff --check` passed. The independent review had one
Important finding, fixed with a failing regression followed by the full green
suite; no other Critical/Important or Minor findings were reported.

## Dokploy development rollout

Deploy matching API and worker backend code containing migration **0013**. In the
updated `api-dev` container terminal run each command separately:

```sh
/app/.venv/bin/python -m fitcheck_backend.storage.migrate upgrade
/app/.venv/bin/python -m fitcheck_backend.storage.migrate check
```

Expected schema check: `No new upgrade operations detected.` Application startup
does not run migrations. Restart/start the matching API and worker after migration;
check `/health/live` and `/health/ready` return 200. No new environment variables or
frontend changes. Check the existing metrics-enabled/environment settings of both
backend services: an intentionally disabled writer correctly limits coverage.

Do not disable collection, remove domain data or invoke cleanup in development to
reproduce F01. Controlled interruption tests use only disposable local PostgreSQL.
