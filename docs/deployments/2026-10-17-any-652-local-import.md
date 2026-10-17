# ANY-652 local import validation and rollout

Implementation: `feat/any-652-local-import`, base591f3c3, isolated worktree
`.worktrees/any-652`. Spec and plan are under `docs/superpowers/` with matching
`2026-10-17-any-652-local-account-import` names. Written spec and native execution
were approved in conversation. The website migration wizard remains ANY-653.

## Local verification

- Baseline:797 backend tests passed,1 paid canary skipped.
- Full implementation suite:815 passed,1 paid canary skipped, PostgreSQL17.
- Frontend:407 passed,3 skipped; TypeScript, ESLint and webpack build passed.
  The first sandbox build could not download the existing Google fonts; the
  authorized network-enabled rerun passed. No frontend routes changed.
- OpenAPI and generated TypeScript updated together. The shared fixture is
  produced by the real client exporter and consumed through API/worker tests.
- Disposable project `fitcheck-any652`, localhost55464; smoke uses separate
  `fitcheck_any652_smoke_test`. No personal data, real credentials or paid calls.
- Both Docker images built. API/worker healthchecks passed. Actual localhost HTTP
  bootstrap/login, import/polling, history and repeat import passed through a
  standalone worker: first imported1, next skipped1, legacy snapshot preserved.
  Alembic reported no drift and provider-call rows were zero.
- Initial smoke used a reserved `.invalid` email that the normal email validator
  rejects. Corrected only that disposable fixture to `example.com` and reran
  successfully; production validation was preserved.

## Execution rulings

- Reuse root locked virtualenv/node_modules with explicit worktree source and
  subprocess PYTHONPATH rather than duplicate dependency installation. Cost if
  wrong: accidental root imports; wheel/export checks catch source confusion.
- Normalize plan Task headings for the skill parser. Documentation-only cost.
- Run installed Node CLI entrypoints because the pnpm wrapper stalled while
  setting itself up. Cost if wrong: commands must follow future script changes.
- Rename import contract tests to avoid pytest's flat-module collision with the
  existing test_contracts.py. Cost if wrong: old targeted test paths change.
- Unknown historical locale remains null; new reanalysis uses current preference,
  otherwise en. Cost if wrong: new reports default to English for an unset account.

## Shared deployment checkpoint

Not deployed yet at this checkpoint; local validation is not shared health proof.
Before rollout: green review/CI, pause admission, inspect/drain existing jobs,
apply additive0009, deploy matching API/worker, verify schema/heartbeat/readiness
and a nonpaid import boundary, resume admission and restore temporary autodeploy
settings. Record actual commits and runtime evidence here after rollout.

Never downgrade0009 to boot an old service: source-scoped receipts may share IDs
that the older uniqueness cannot represent. Preserve domain/import accounting and
use a compatible forward fix. Existing webhook TLS-chain repair remains separate;
manual deployment is available without disabling certificate validation.

## Final review and fixes

Fresh whole-branch review found no Critical issues. Fixed the two Important input
issues: identifiers are checked for duplicates after canonical trimming before
admission; JSONB-incompatible strings are isolated as invalid row/profile data
and an unusable source identity is rejected400. Both reproduced RED first.
Regraded repeated whole-batch loading as Important because supported max-size
imports could decode roughly10GiB: item fences now omit immutable input, consume
the frozen lease and retain both expiry checks. A real-SQL regression reproduced
RED and passed after the fix. Full backend suite after the single fix pass:
818 passed,1 paid canary skipped. Frontend407 passed,3 skipped; type/lint and both
contract drift checks passed again.

Deferred minor: equivalent timestamp instants written using different UTC-offset
strings produce different receipt hashes and report source_changed. The current
exporter preserves original timestamp strings; this does not overwrite data or
create duplicates. Canonical UTC hashing is a follow-up refinement.

Reviewer exclusions were ruled explicitly: website sign-in/wizard/rendering is
ANY-653 (cost: no migration screen until integration); live rollout is verified
separately by the executor and the certificate repair remains outside scope
(cost: old webhook TLS issue remains); drafts/passwords are not transferred
(cost: drafts remain local and server authentication is required).

Additional execution rulings: move Task6's review/rollout bullet after its local
verification completion to satisfy the whole-branch review ordering (cost: ledger
completion is not deployment evidence); classify repeated batch reads as Important
and omit only the import fence's input column (cost: imports rely on the frozen
lease rather than reloading immutable input).

## Completed dev rollout

Code commit `636503cc1cdd83b611614c90f40bc174e059e4bb` was fast-forward integrated
into dev and pushed. [CI39065599184](https://github.com/NikitaPotapovIt/fitcheck/actions/runs/39065599184)
passed both jobs. The merged local full backend suite passed818 tests,1 paid
canary skipped; one Pydantic alias warning occurred in the existing concurrent
profile-update test. No test failed. The final Docker images were rebuilt and
smoked again: API image523a9fb26726, worker8688e8cf7490, healthchecks passed,
schema0009 matched and provider-call count stayed zero.

All three Dokploy autodeploy switches were disabled before push. API was stopped
through its normal application control to pause all admission, rather than edit
shared environment text. Old worker7334f10635be confirmed schema0008 and zero
active jobs. The exact runner was first tested on disposable0008, then applied
under the existing migration advisory lock. Migration payload SHA-256:
`9a071b623485c09cc11298a098ff0e8032bb20f3f37e7f415bf4a40e6c38212d`.
The runner repeated upgrade as a no-op and confirmed unchanged existing counts:
owners3, users/jobs/analyses/provider_calls/import_entries0. No live records were
deleted, reset or downgraded.

Worker application `uGz_HiVcXoTo1Rid214vn` deployed636503c in24 seconds; runtime
container `335f53eef676` passed schema check and heartbeat. API application
`4Dfp-p3ua4kBSxLZ_mczn` deployed the same commit in27 seconds; runtime container
`8d8e6e005c5a` confirmed jobs=true, guest=true, schema0009 and zero provider calls.
Both match all151 packaged Python source files (excluding migrations), canonical
digest `4224ba053d61fb128d4b04a7c238a4eed5be0d0c443edca773a3e623220f9055`.

Inside the live API container, the previously tested rollback smoke imported1
record and skipped1 replay. The enclosing database transaction was rolled back;
an independent connection confirmed that the synthetic owner was absent and all
prior row counts were unchanged. This is a live repository/DB check; the complete
HTTP login/import/polling/worker flow was tested on disposable Docker services.
External HTTPS certificate-verified checks returned readiness200/database_ready
and401 for unauthenticated import POST/GET. No paid provider request was sent.

Operational ruling: stop/redeploy API instead of changing the jobs flag in the
environment editor; the same admission pause is achieved without touching secret
configuration. Cost: a short maintenance interval returns502 until the new API is
ready. No `.env`, shared certificate or other user's data was changed.

The website image needs no deployment for these exported library/backend
boundaries; its migration UI remains ANY-653. All three autodeploy switches are
restored after the final documentation push. This manual rollout does not repair
the separate webhook TLS-chain problem. Task-owned disposable local containers
and volumes were removed after verification.
