# FitCheck development OpenAI rollout

Prepared 2026-10-16. **Local implementation verified; external rollout pending.**
This record covers the transition from the previously deployed DeepSeek fleet to
OpenAI `gpt-6-luna`. It does not supersede historical evidence in the
[metrics rollout record](2026-10-14-fitcheck-metrics.md) or claim a provider push,
remote CI pass, image deployment, live 0007 migration or account/model access.

## Verified local evidence

| Scope | Evidence |
| --- | --- |
| Shared Python configuration, admission and worker boundary | Local commit `699a3a4`; independent task review approved spec and quality |
| Website analysis/suggestions and server configuration | Local commit `1c8082b`; independent task review approved spec and quality |
| Versioned usage/pricing, migration and contracts | Local commit `870c17e`; independent task review approved spec and quality |
| Full backend at `870c17e` | 705 passed, 1 paid canary skipped, 25.53 seconds; guarded disposable PostgreSQL |
| Full frontend at `870c17e` | 397 passed, 3 paid live tests skipped, 3.42 seconds |
| Frontend validation at `870c17e` | Full ESLint, TypeScript and production webpack build passed |
| Task 3 artifact/storage validation | OpenAPI and generated TypeScript drift checks, packaged-wheel migration head 0007 and migration/schema checks passed locally |

The ignored root `.env.local` already has exact `OPEN_AI_MODEL=gpt-6-luna`;
root changed the model assignment only and preserved credential values. No key
value belongs in this record or Git. Provider tests exercised installed SDKs with
mock transports and documented usage-shaped fixtures. No paid generation ran.

Root additionally verified all three Dokploy autodeploy switches ON → OFF for
this provider rollout on 2026-10-16, without changing environment/admission.
An actual Alembic drift check against explicitly guarded disposable `fitcheck_test`
at head 0007 reported “No new upgrade operations detected.” Local API/worker
Docker builds at `870c17e` were running at preparation time; no completed build
or digest is claimed here. No provider push had occurred.

Fresh whole-branch review, final runtime/documentation SHAs, both final backend
image builds, final diff checks and all external gates below remain to be recorded
by the rollout operator. Individual task approval is not whole-branch approval.

## Server configuration to prepare

| Recipient | Required provider configuration |
| --- | --- |
| Website | Supplied `OPEN_AI_KEY` in server secret storage; `OPEN_AI_MODEL=gpt-6-luna` |
| API | `OPEN_AI_MODEL=gpt-6-luna` for admission; no provider key required |
| Worker | Same supplied `OPEN_AI_KEY` in server secret storage; `OPEN_AI_MODEL=gpt-6-luna` |

Do not regenerate the supplied key, expose it in browser/public variables, print
settings or raw provider errors, or include it in evidence. Unsupported model
values fail safely. Transfer the key only through supported secret configuration;
if the access mechanism requires action-time confirmation, request it when the
concrete recipients and changes are ready to apply. Credential transfer has not
been performed for this migration.

Preserve database/auth/origin and metrics configuration on every service. In
particular, retain development collection scope and independent database scope,
bridge/cookie credentials and campaign allowlists. Preserve the website's tested
`NIXPACKS_START_CMD=sh ops/dokploy-website-start.sh` and
`FITCHECK_DOKPLOY_METRICS_GATEWAY=true`; the startup helper maintains the verified
single-host metrics gateway route after container replacement. Replacing the
startup command can break collector reachability. Recheck the route and normal
certificate-verified HTTPS after deployment without exposing credentials.

Keep obsolete deployed DeepSeek credentials available to the old fleet while
frozen work is draining. Remove obsolete active variables only after successful
OpenAI startup/configuration verification and a safe drain/rollback decision;
historical deployment records and accounting rows remain unchanged.

## Planned controlled rollout — not executed

1. Finish whole-branch review and final local checks/image builds. Record exact
   runtime commit and image identifiers. Verify **website, API and worker
   autodeploy OFF before pushing provider code**; the metrics predecessor restored
   all three switches ON. Push reviewed `dev`, await CI success at the exact
   runtime SHA, and record the run URL. No fleet switch on a failed/stale CI run.
2. On the existing API, set `FITCHECK_JOBS_ENABLED=false` and verify admission is
   disabled while authenticated GET remains available. Apply the environment
   change using Dokploy **Reload**, retaining the pinned pre-migration API
   runtime/image; record and verify the same old SHA/image before and after.
   Do not use a deploy/rebuild of the newly pushed branch to disable admission.
   If Reload cannot retain that pinned runtime, stop until it can be applied
   safely. Preserve auth and metrics state. Inspect **all nonterminal jobs**, grouped by frozen envelope provider,
   model and policy version, with counts and timestamps only. Treat legacy or
   missing envelopes as incompatible until resolved; do not output task/profile
   payloads. Let the existing matching DeepSeek worker drain. Reinspect after
   draining. If incompatible work remains, stop the switch and retain the old
   worker/key; never delete, mutate or reinterpret those jobs to force zero.
3. With admission still off and the old worker drained/stopped, use the approved
   migration runner and target database secret to apply additive
   `0007_provider_usage_basis` from the observed head. Use the established storage
   runner (`python -m fitcheck_backend.storage.migrate upgrade`), then its `check`
   command. Record runner identity, observed before/after head, success and drift
   result without secrets. The predecessor's last verified remote head was 0006;
   reread it rather than assuming it remains so. Preserve 0001–0006, domain rows,
   historical costs and telemetry. Do not reset or downgrade the database.
4. Prepare/save the server configurations above through supported secret stores.
   Deploy the new **API registry first**, retaining `FITCHECK_JOBS_ENABLED=false`.
   Verify exact runtime SHA, schema 0007, readiness, model `gpt-6-luna`, auth and
   telemetry scope. Inspect credential presence only as booleans; the API should
   not receive the provider key. Do not enable admission yet.
5. Deploy the matching **worker** with `OPEN_AI_MODEL=gpt-6-luna` and supplied
   server key. Verify exact runtime SHA/image, schema, process/health marker,
   key-present boolean and registry/policy compatibility
   (`openai`, `gpt-6-luna`, `fitcheck.llm.policy.v2`). Confirm no incompatible
   nonterminal job remains. Startup and mocked boundary evidence suffice for
   this gate; do not create a paid job as a health check.
6. Only after compatibility is confirmed, restore API admission to its intended
   enabled state. Verify external readiness and anonymous job rejection without
   executing a model request. Preserve authenticated read and ownership checks.
7. Deploy the **website last**, with matching exact model/key and preserved
   origin/metrics/startup settings. Verify the exact runtime SHA, normal page
   rendering, configuration booleans and collector reachability. Use mock or
   disposable test-scope evidence for OpenAI provider/model attribution, attempt
   accounting and unknown-cost coverage; label fixtures as synthetic. Do not
   present a mock as a live OpenAI response or contaminate development cohorts.
8. Append actual migration, CI, images, configuration/health and report evidence.
   Remove obsolete active DeepSeek variables only after the preceding gates pass.
   Commit/push final reviewed documentation and verify its CI as applicable.
   Restore all three autodeploy switches to their intended ON state only after
   the controlled rollout and final documentation push; verify and record each
   state. Do not leave an accidental automatic partial-fleet transition enabled.

The operator report remains CLI-only; there is no public cross-account report
endpoint. Use `python -m fitcheck_backend.metrics report` with explicit start/end,
`--timezone Europe/Moscow`, `--environment test` for synthetic fixtures and the
appropriate `--population visitor|account|all`, writing to an operator-selected file.
Select a bounded interval with proven coverage and no future end. Record aggregate
provider/model/purpose/outcome/basis/coverage findings without personal content.
Recheck unauthenticated collector access rejection and absence of a public report
route. Actual development observation should use an ordinary non-paid page visit.

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

## External evidence still required

Pending: whole-branch approval; final local image/diff evidence; provider push and
exact-SHA CI; final autodeploy restoration; remote job inspection/drain;
secret-store transfer authorization/application; migration runner and live head
0007/drift; matching API/worker/website images and SHAs; external health, model and
configuration booleans; anonymous rejection; synthetic provider attribution and
report coverage; replacement-container metrics routing; final docs push and
restored switches. No remote/provider step is marked complete here.

Actual key/account access, live response compatibility, grounding quality and
billing are **unverified** by these mock/startup checks. All optional paid tests
remain skipped. A live canary requires a separately approved concrete spend cap
before execution; record its status and limits if subsequently authorized.

## Official sources checked during implementation

- [GPT-6 Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna): exact identity, Chat Completions, reasoning effort and context constraints.
- [Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): output cap, JSON format, raw usage and actual response service tier.
- [OpenAI pricing](https://developers.openai.com/api/docs/pricing): versioned Standard/global text rates and unsupported premium contexts.

These are the official URLs verified in Tasks 1–3 on 2026-10-16. This preparation
pass did not refetch them or make any provider request.

## Additional local build evidence

Both local Docker builds at source `870c17e` subsequently completed:

| Image | Config/image ID | Manifest-list digest |
| --- | --- | --- |
| `fitcheck-openai-api:20261016` | `sha256:913a46867f8773771134413d7beb89f1c43a7dd1f00fe60309121b189557c27c` | `sha256:6aa7a090935ce43de4790fda7ee20baa90cbe284d0e9bd822328e5e59e90b44d` |
| `fitcheck-openai-worker:20261016` | `sha256:a5ada6ad5987d82321eb667d909f7e42a402750cc380da2bd721d5a706fee5ba` | `sha256:fefd37ed47a123b681dfc8c49306c01d3bc59f35dc5d59629cc03e2f3fdf9b0a` |

Each image ran its packaged Python imports/policy/schema probe with `--read-only
--network none`, exit 0: schema head **0007**, provider **openai**, model
**gpt-6-luna**, policy **fitcheck.llm.policy.v2**, no provider key supplied. API
probe imported the metrics CLI; worker probe imported its runtime. No provider
or database connection was made by these probes. These are local image checks,
not remote deployment or account access proof.
