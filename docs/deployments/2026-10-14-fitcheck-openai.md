# FitCheck development OpenAI rollout

Updated 2026-10-17. Reviewed runtime `d30b19b4612f403629197a000a47896abc04a221`
is deployed to the existing development API, worker and website. All three use
`OPEN_AI_MODEL=gpt-6-luna`. The supplied key is saved only in the website and
worker server configuration, following the user's action-time approval. No key
value is recorded here, in Git, or in public environment variables.

The [preceding metrics rollout](2026-10-14-fitcheck-metrics.md) remains the record
for metrics Tasks 1–8, including its twenty execution rulings and real-bridge
acceptance evidence. This record covers the matched provider transition.

## Review, source and CI

Tasks 1–3 each passed independent specification/quality review. Whole-branch
review found two Important issues: Python OpenAI SDK debug logging could disclose
request content, and exact-head-0006 backend images cannot run against schema
0007. One final fix wave in `d30b19b` addressed both. The single scoped rereview
approved both fixes with no new findings; no unresolved Critical/Important finding
is deferred. Operational logs remain enabled while provider SDK logs are isolated.

[Runtime CI](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/39039672986)
passed both verify and backend jobs at the exact runtime SHA. All three Dokploy
autodeploy switches were verified OFF before the provider push and remained OFF
through the controlled rollout. Deployment evidence was pushed as `3e844ca`;
only afterward, the website, API and worker switches were each restored OFF → ON
and verified in the UI on 2026-10-17. All three intended final states are ON.

| Local validation | Result |
| --- | --- |
| Final full backend, guarded disposable PostgreSQL | 707 passed, 1 paid canary skipped, 30.70 seconds |
| Frontend | 397 passed, 3 paid live tests skipped, 3.42 seconds |
| Frontend checks | Full ESLint, TypeScript and production webpack build passed |
| Contracts/storage | OpenAPI/generated TypeScript drift, packaged wheel head 0007 and Alembic schema checks passed |
| Installed SDK boundary | Mock transports exercised real LiteLLM/OpenAI SDKs, exact destination/params, one-send limits, cancellation, concurrent isolation and safe errors |
| Final SDK logging regression | Fresh subprocess DEBUG-before-import cases: 2 RED failures → 18 focused/89 covering passes |

The full backend emitted one Pydantic body-alias warning in unchanged concurrent
profile tests. A focused rerun with all markers and warnings as errors passed
(1 test, 0.46 seconds); the warning was not reproduced, its cause is unproven,
and it did not block the approved final review.

Final local images built from `d30b19b`:

| Image | Config/image ID | Manifest-list digest |
| --- | --- | --- |
| `fitcheck-openai-api:20261017` | `sha256:e6ccf6e783b7a31c61305dd5291d32c597cea2591b11658a788b7f904e35a8c4` | `sha256:46a04062e7618d955c61eae8e26a7bb48e1b0ed63a38853379142bf88fcedf5e` |
| `fitcheck-openai-worker:20261017` | `sha256:7d579d7154baa487c35bfa95a5fa2f90bad002929d0f74109152e3f3b9c1158e` | `sha256:e9af21f222caa443d3f471f43592377abb13bae6ba2f6e2c9abcf29398e24019` |

Both packaged probes passed with `--read-only --network none`, schema head 0007,
OpenAI/Luna/policy-v2 and no provider key. These are local image identities;
Dokploy builds its own remote images, verified by deployment SHA and source hashes.

## Executed migration and fleet transition

The old API received `FITCHECK_JOBS_ENABLED=false` through **Reload**, retaining
the pinned pre-migration runtime. Container `02701b499a78` reported schema 0006,
DeepSeek policy, auth/metrics enabled, both collection/database scopes development,
and no nonterminal jobs (`[]`). Its 115-file Python source manifest was
`c0018ab4fab3c0f7f1c4a84bfc324bb1421f41f200fe285b951dc5f6de7f35a2`.
The drained old worker was stopped before migration; the UI showed Start.

A pinned additive migration adapter used the installed migration runner's advisory
lock and transaction. It verified all frozen 0001–0006 migration hashes, verified
new 0007 SHA256 `88cba73d3fdfb463d4559771ab3c946b1a79b3af4a837c9f7c2061afa04ca745`,
refused nonterminal jobs, and upgraded a temporary copy of the migration directory
without modifying the installed old package. Command SHA256:
`41300b09be23a0eab2396d0c570824879bdb9a967bfbdbc55268179d317c281c`.
Before remote use, a disposable transactional schema proved drain refusal,
0006→0007, repeated no-op and row/cost preservation, then rolled back.

Observed live output:

```text
MIGRATED 0006 -> 0007 ROW_COUNTS_PRESERVED True HISTORICAL_COSTS_PRESERVED True
```

Owner, job, provider-call, journal and website-attempt row counts and both ledger
cost sums were checked atomically. No reset, downgrade, queued-job rewrite or
historical cost rewrite occurred. The new API's packaged runner subsequently
reported **No new upgrade operations detected**.

API deployed first with admission off, worker second, then admission was restored
and website deployed last. Each Dokploy deployment completed at exact `d30b19b`.

| Service | Observed runtime evidence |
| --- | --- |
| API | Initial new container `c2dc7a97cd22`; after admission Reload `6e5a67b31746`: schema and packaged head 0007, model `gpt-6-luna`, provider key absent, jobs/auth/metrics true, both scopes development |
| Worker | Initial new container `64edcc1e7b5a`; after obsolete-env removal Reload `428a870ccd7f`: health true, packaged head 0007, model `gpt-6-luna`, provider key present, policy provider openai, both scopes development, no nonterminal jobs |
| Website | Initial new container `16fd42ec9606`: model `gpt-6-luna`, provider key present, metrics bridge/cookie keys present, development scope and correct collector destination; source hashes matched local runtime |

Both new backend packages had exactly 116 non-migration Python files and source
manifest SHA256 `bbaaf5c5e81d252f07b68073327394b57785c144e4103380c426bb5946464615`,
matching the local runtime. Website source SHA256 checks matched:

| File | SHA256 |
| --- | --- |
| `lib/analysis/openai.ts` | `c3c9ca83e9a848c345b48e4545e0015b00ee8b6e1006b5be1539a173102d7819` |
| `lib/skill-suggestions/openai.ts` | `fa6624e22139c76cebe9bf6cae2e8fa878502d1d74a196dd9c416b947cc034f1` |
| `lib/metrics/pricing.ts` | `cfa478b8889fbbc5b571180c7a5fd1186d8e7236edb870198a3a0daf68bf8604` |
| `ops/dokploy-website-start.sh` | `0735b90b01589a676b253bfedbfd7b13fa46ce6c0842a75f3301967b66a9f3b8` |

## Health, telemetry and coverage

API loopback checks after admission restoration: readiness 200, anonymous POST
`/v1/analysis-jobs` 401, anonymous POST `/internal/metrics/events` 401,
`/internal/metrics/report` 404. There is no public cross-account report endpoint.

Website retained `NIXPACKS_START_CMD=sh ops/dokploy-website-start.sh` and
`FITCHECK_DOKPLOY_METRICS_GATEWAY=true`. Certificate-verified HTTPS from the
replacement website container to the configured collector returned readiness 200
(58 ms initially, 57 ms after Reload); no TLS verification bypass was used.
Chrome rendered the ordinary development landing page without generating an
analysis or suggestion. The persisted development page-view count increased
**1 → 2**; the bounded operator acquisition report returned one visitor with
availability true (the same retained browser identity, so no new visitor was invented).

Synthetic accounting proof comes from the guarded disposable tests, **not a live
OpenAI response**. Backend and website attempts both retained OpenAI/Luna and
`openai.luna.2026-10-16` attribution, cache-write cost `0.000000125` exactly,
separate rows without fanout, and failed-generation/audit costs in successful
operation expenses (`0.000000375` across three calls). Shared Python/TypeScript
fixtures cover 22 known/unknown usage cases. Missing counts, unsupported actual
tier/model/context and transport failures without usage remain unknown with
coverage/reasons. Historical DeepSeek costs stay estimated/unversioned and unchanged.
No synthetic attempt was inserted into the development cohort for this proof.

Obsolete active DeepSeek variables were removed from ignored `.env.local` and
Dokploy website/worker configuration only after OpenAI startup checks. The supplied
OpenAI key was preserved. Worker replacement reports zero DeepSeek variables.
Nixpacks embeds build environment into its image: a website Reload still exposed
two old variables, so a fresh image build was started with the cleaned configuration;
the clean-image deployment completed at `d30b19b`, container `92cb5c3b1c05`.
It reports **zero DeepSeek variables**, model `gpt-6-luna`, key present, preserved
metrics/startup flags and certificate-verified collector readiness 200 (58 ms).
Historical deployment records are retained.

## Rulings I made

1. Widen ledger cost precision to `NUMERIC(24,12)` and serialize operator-report
   Decimal money as decimal strings. One cache-write token costs `0.000000125`,
   which the old precision cannot preserve. Tradeoff: additive migration and
   operator consumers must accept strings; product result contracts stay unchanged,
   and downgrade refuses lossy narrowing.
2. Preserve schema 0007 and reject direct rollback to exact-head-0006 backend
   images. Their startup/readiness gates cannot accept 0007. Provider rollback
   needs a separately reviewed 0007-compatible artifact; otherwise keep admission
   off and repair forward. Tradeoff: recovery is less immediate and admission may
   remain unavailable during repair; no data/schema bypass or historical rewrite.

The predecessor's twenty rulings are preserved in the linked metrics record.
No deferred review finding remains; live account/model access, response quality
and invoice verification remain explicit untested coverage, not review approval.

## Pricing and compatibility

Snapshot `openai.luna.2026-10-16` was checked against official documentation on
2026-10-16. USD per million text tokens: uncached input 0.10, cached input 0.01,
cache write 0.125, completion 0.50. Cache subdivisions do not add to total input;
reasoning already included in completion is not charged twice. Only known actual
Standard tier (`default`), global processing and at most 272,000 input text tokens
are priced. Missing usage/cache counts, unknown actual model/tier, unsupported
region/modality or larger contexts yield **unknown with a reason**, never zero or
a guessed premium. Costs are estimates, not invoice verification. See
[backend accounting operations](../../backend/README.md#telemetry-and-operator-reports).

Migration 0007 widens both ledger cost columns to `NUMERIC(24,12)` and adds
nullable provenance fields without rewriting historical values. One cache-write
token remains exactly USD `0.000000125`. Operator report JSON now serializes
Decimal money as decimal **strings**; downstream operator consumers must accept
strings without converting through binary float. Website attempt DTOs accept 12
fractional places; product result contracts are unchanged. Historical DeepSeek
costs retain estimated/unversioned provenance. A downgrade refuses lossy narrowing.

## Rollback and stop conditions

Disable new admission before any rollback; disable metrics ingestion/collection
if needed while preserving its stored observations. Inspect all nonterminal
frozen versions again. Before migration 0007, an abort retains the pinned old
API/worker runtime and DeepSeek key against the unchanged pre-migration schema.
If old jobs cannot drain, keep this matching fleet/key usable and admission off;
do not proceed to migration. Re-enable only after verifying that retained fleet's
schema, health and frozen-version compatibility.

After 0007 is applied, **do not restore the old exact-head-0006 backend images**.
Their API readiness requires its packaged schema head exactly, and their worker
startup schema check cannot accept 0007. An additive migration does not make
those images compatible. Keep admission disabled and retain the reviewed current
0007-compatible API/worker runtime; if it is not running yet, start that reviewed
compatible runtime and repair forward. Preserve authenticated GET on the
schema-compatible API where healthy. Recovery is less immediate, and job
admission can remain unavailable while repair is completed.

A provider rollback after 0007 requires a separately reviewed artifact carrying
0007 and the intended provider registry/transport. Validate its startup/schema
checks against a disposable 0007 DB and compatibility with all intended frozen
jobs before use. No such old-provider artifact is prepared or claimed usable
here. Drain OpenAI jobs with the matching OpenAI worker/key before switching to
any otherwise compatible artifact; if draining cannot finish, retain the matching
runtime/key and admission off. The same frozen-job rule applies to DeepSeek work
during forward rollout. Restore provider/model, registry, origins and
metrics/startup configuration consistently only within a reviewed compatible
fleet. Preserve 0007, all domain/telemetry rows, immutable envelopes and costs.
Never bypass schema gates, reset/downgrade the DB, delete jobs or rewrite
historical work to make old images boot. Record the final autodeploy state explicitly.

## Limits and finalization

No paid OpenAI request or live canary was run. Actual key/account access to the
model, live response compatibility, grounding quality and billing remain
unverified by startup/mock checks. All four opt-in paid tests remained skipped.
A live canary requires separate approval of a concrete spending cap.

External HTTPS readiness returned status ok with database ready. The clean-image
website gate, real non-paid visit, migration, matching fleet and configuration
gates are complete. Evidence was pushed as `3e844ca`, then all three autodeploy
switches were restored and verified ON. This final documentation update changes
no runtime source; subsequent automatic builds use the same reviewed code and
cleaned server configuration.

## Official sources checked during implementation

- [GPT-6 Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna): exact identity, Chat Completions, reasoning effort and context constraints.
- [Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): output cap, JSON format, raw usage and actual response service tier.
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing): versioned Standard/global text rates and unsupported premium contexts.

These are the official URLs verified in Tasks 1–3 on 2026-10-16. This preparation
pass did not refetch them or make any provider request.
