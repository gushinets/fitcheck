# ANY-750: metrics capacity and delayed 429 retries

Date: 2026-10-25. This document describes local implementation and synthetic verification; deployment/server acceptance has not been performed.

## Configuration and rollout

No schema migration or new dependencies. Deploy the backend first, then the website, so the increased relay budget does not encounter the old collector's 60/minute limit. Restart the relevant processes after changing configuration. Existing credentials and enabled/environment settings remain required.

| Setting | Default | Scope |
| --- | ---: | --- |
| `METRICS_RATE_LIMIT_PER_MINUTE` | 600 | HTTP POST + DELETE admissions per Next process |
| `METRICS_VISITOR_RATE_LIMIT_PER_MINUTE` | 30 | Admissions per verified visitor per Next process |
| `FITCHECK_METRICS_RATE_LIMIT_PER_MINUTE` | 1200 | All internal metrics HTTP admissions per environment, shared in PostgreSQL |
| `FITCHECK_METRICS_VISITOR_RATE_LIMIT_PER_MINUTE` | 60 | Admissions per visitor per environment, shared in PostgreSQL |

Limits are positive integers up to 100000. Both sides use fixed UTC minute windows; 429 includes seconds until the next window. POST and DELETE share their respective budgets. Website-server events and attempts also consume collector capacity; a batch counts as one HTTP admission and once for each distinct visitor it contains. Rejected visitor requests do not consume aggregate admissions. Existing cleanup removes expired rate buckets on traffic; new visitor rows are created only for admitted requests. Relay counters retain at most the aggregate number of visitor entries per minute. No IP addresses or raw cookies are stored in counters; persisted visitor keys are digests.

Default capacity supports two Next processes at 600 requests/minute each; the collector ceiling includes website-server traffic, so reserve headroom for it. The normal acceptance workload is **31 active visitors × (two 30-second pulses + two page/action requests) = 124 requests/minute**, leaving 476 relay admissions and 1076 collector admissions of headroom for this single workload. With additional processes/workloads, explicitly configure both aggregate ceilings and shared visitor ceilings. A shared collector limiter prevents replicas from independently multiplying the collector budget.

Fairness is within this configured workload: a burst from one stable signed visitor stops at its visitor ceiling and leaves other visitors' aggregate capacity available. New/rotated visitor identities still share aggregate capacity; cookie churn or traffic exceeding the aggregate ceiling can produce 429. These controls are not a device identity or a guarantee against arbitrary distributed load.

## Browser delivery

Collector 429 and Retry-After pass through the bridge/relay without treating the request as a committed receipt. The relay still issues the new visitor's signed cookie on 429, preserving the subject during replay. Other callers of the bridge retain the existing boolean receipt API.

The browser accepts nonnegative integer Retry-After seconds and HTTP-date values. Missing/invalid values wait 60 seconds; zero/past dates wait at least one second to prevent tight loops. It keeps original event IDs/properties and waits before retrying. Further flush/activity/visibility calls cannot bypass the cooldown, including when one batch exhausts retries and another starts. Three attempts are allowed per batch, with a 120-second lifetime starting when that batch is taken for draining, including waiting inherited from a preceding batch. A valid delay exceeding that remaining lifetime fails the batch explicitly; it is never shortened to retry early. Each transport attempt retains the 2.5-second deadline.

The memory-only queue holds at most 100 events including the active/waiting batch; batches retain the existing 20-event / 32768-byte limits. Overflow drops older queued events. `stats()` includes queued/in-flight events, delivered, failed and dropped counts; loss is reported through `fitcheck_metrics_client_loss` with numeric counters only. Disposal and identity reset cancel waits; deletion clears old observations before rotating identity and does not wait out a retry timer. Browser erasure remains a single bounded best-effort request, as before; it does not gain a persistent retry queue. Website-server boolean bridge callers also remain best effort and do not acquire browser retry semantics.

Reload, tab close, process shutdown, exhausted retries and overflow can still lose observations. There is no persistent outbox or completeness guarantee; do not interpret missing observations as proof of zero conversion. Backend receipts still require committed accepted+duplicate counts for the complete submitted batch.

## Verification

Frontend controls in `lib/metrics/client.test.ts`, `lib/metrics/rate-capacity.test.ts` and `app/api/metrics/route.test.ts` cover:

- 31 real metrics clients with foreground activity, two pulses each and page/action traffic through two independent relay handlers: 124 HTTP requests, no failed/dropped observations.
- Actual browser transport → relay → collector-boundary 429 → delayed retry with the same visitor and event IDs, including duplicate receipt acknowledgement.
- A noisy signed visitor, aggregate/window limits, shared POST/DELETE budget and invalid configuration.
- Retry seconds/date/fallback parsing, oversized delays, three-attempt exhaustion, cross-batch cooldown, bounded queue and dispose/reset/deletion cancellation.

PostgreSQL tests in `backend/tests/metrics/test_limits.py` and `backend/tests/integration/test_metrics_http.py` cover shared worker admission, concurrent aggregate admission, fairness, expiry, HTTP 429, normal 124-request ingestion, and original-ID replay deduplicating in the real journal. Browser capacity controls use a synthetic committed collector boundary; PostgreSQL controls independently exercise the real HTTP collector/database. No paid LLM calls are used.

Run frontend checks:

```sh
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js app/api/metrics lib/metrics
```

Run backend unit tests from `backend` using `.venv/bin/python -m pytest -q`. For database controls use the guarded disposable database (`FITCHECK_TEST_DATABASE_URL`, database name must end in `_test`):

```sh
.venv/bin/python -m pytest tests/metrics/test_limits.py tests/integration/test_metrics_http.py -m integration -q
```

On the deployed environment, repeat the synthetic normal workload and 429 recovery using non-user data, inspect journal IDs/duplicate receipts and sanitized loss counters, and record commit, environment and actual counts before claiming server acceptance.

### Local results

- Frontend: 546 passed, 3 skipped (53 passing files, 2 skipped).
- Backend default suite: 688 passed, 2 skipped; 409 integration tests deselected by the default marker. One SDK/Pydantic ReadOnly warning remains.
- Expanded PostgreSQL metrics integration: 81 passed, including lifecycle/identity/erasure regressions.
- TypeScript, full ESLint and `git diff --check`: passed.
- Independent review: one late-timer lifetime finding reproduced and fixed; follow-up review reported no remaining Important/Critical issues.

The full frontend run exposed an existing asynchronous assertion race in `test_ordered_local_registration_profile_analysis_view_events`; it now waits for the result-view effect to emit before checking its ordered event list. No result-emission product behavior was changed as part of this adjustment.
