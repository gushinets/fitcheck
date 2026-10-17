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
