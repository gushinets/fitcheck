# ANY-648: server-owned LLM gateway

Implemented, pushed to `dev` and deployed on 2026-10-12, code commit
`9604878129d447d0d55c478b047b89cc3d311158`.

Fit analysis and skill suggestions now have Python application services using
owner-scoped profile revisions and server calibration memory. PydanticAI owns
structured generation/validation and report grounding; LiteLLM is behind the
accounted provider gateway. Every physical attempt has committed technical metrics,
separate transport/semantic retry indices and prompt/schema/policy versions.
Generation and audit share the call cap/deadline. Server results include threshold
70 and server-rendered strength evidence; legacy JSON payloads remain accepted.

Validation of the final implementation:

- 477 backend tests passed, including PostgreSQL storage/service/HTTP integration.
- One paid live-model canary skipped: explicit opt-in/key were not supplied.
- 298 website tests passed; three optional live tests skipped.
- TypeScript, ESLint, OpenAPI/TS drift, migration drift and diff checks passed.
- Independent whole-branch review found Retry-After loss in the installed LiteLLM
  error mapper. Four regression failures were reproduced; response-boundary capture
  now preserves the delay for 429/5xx and refuses a retry beyond the deadline.
  The full backend suite passed after the fix. No deferred review minors.
- [CI completed successfully, including website build](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/38293512219).

## Development rollout

Before API restart, applied the reviewed additive `0002` migration through Alembic
in the previous running container. A temporary copy of its packaged migration
directory included the exact new revision; the existing migration connection/lock
runner upgraded it to `0002`. This allowed schema-first rollout without requiring
the old package to know the new revision. The same command was verified against
disposable PostgreSQL first. No reset or data deletion occurred.

Dokploy `fitcheck-api-dev` reports Done for the code commit above; build took 22s.
New running container: `6096386a5529`.
Inside it, Alembic reported no new upgrade operations, `SCHEMA_CHECK_OK 0002`, and
`LLM_IMPORT_OK deepseek-v4-flash 1.105.0 1.107.7` (LiteLLM/PydanticAI versions).
External checks at `https://dev-fitcheck-api.dokploy.gcexp.ru` confirmed liveness
and readiness 200, database ready and the existing extraction route implemented.
Profile/draft anonymous requests returned 401. Website returned 200.

No provider generation was run against the deployed database. Live model quality
and account/model availability remain unverified by the deliberately skipped canary.
Jobs/worker/public LLM admission/publication and website switching remain
ANY-649/650/651/653. Competition scoring and generated fit conditions remain
ANY-575/576. The new gateway is ready for the future worker; the website continues
using its existing flow until integration.

## Execution decisions

- Worked in the current `dev` checkout following the user's accepted inline workflow;
  tradeoff: no separate local worktree isolation.
- Encoded model input as JSON rather than hand-built text lines to frame instructions
  and newlines as data; tradeoff: wording-sensitive live behavior requires a canary.
- Excluded Python `.venv` directories from root ESLint because LiteLLM includes vendor
  JavaScript; tradeoff: code mistakenly placed inside a virtualenv is not linted.
- Deferred job/publication/UI behavior to its assigned tasks; consequence: these
  backend services are not yet connected to the website.
- Deferred competition/condition generation to their product tasks; consequence:
  competition does not change scores and no fit condition is generated yet.
- Did not claim live-provider quality/availability without an explicitly enabled
  paid canary; consequence: deterministic tests cannot establish either property.
- Verified deployment separately after immutable-code review; tradeoff: the reviewer
  did not assess external deployment state, which the checks above establish.
