# FitCheck

FitCheck is a bilingual service for checking whether a freelance task fits a freelancer profile. A user can load any public task URL or paste its text, review the extracted details, and send the task to an LLM for a Fit Score, strengths, risks, and a GO / NO-GO recommendation. The flow is designed for repeated use throughout the day while browsing new tasks.

The website supports English and Russian with a manual RU / EN switch. Local accounts, profiles, drafts, analysis history, and score corrections are stored in IndexedDB in the current browser. The website server receives the current extraction or analysis request. Optional telemetry stores bounded technical observations and provider accounting separately; it does not upload local account, profile, draft, or task content.

## Requirements

- Node.js 22 or newer
- pnpm 10
- An OpenAI API key with access to `gpt-6-luna` and available balance

## Install and configure

```bash
pnpm install
cp .env.example .env.local
```

Set the server-side key in `.env.local`:

```dotenv
OPEN_AI_KEY=your_server_side_key
OPEN_AI_MODEL=gpt-6-luna
ALLOWED_ORIGINS=http://localhost:3000
```

Keep `OPEN_AI_KEY` server-side; never use a `NEXT_PUBLIC_` alias or put it in client-side source. The exact allowlisted model is `OPEN_AI_MODEL=gpt-6-luna`; unsupported model values fail safely. Preserve the supplied credential rather than regenerating it.

## Run the website

```bash
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000), create a local account, complete the freelancer profile, and add a real task.

URL import is best-effort. FitCheck accepts arbitrary public HTTP(S) pages, blocks private/internal network addresses, limits redirects and response size, and extracts readable task content. Pages that require authentication, execute content only in the browser, or block automated requests may not load; paste the task text manually in that case.

## Verify

```bash
pnpm test
pnpm typecheck
pnpm lint
pnpm build:web
```

Skill proficiency is saved per profile skill as Primary, Confident, or Basic.
Older profiles keep an unspecified level until the user chooses one. Analysis
uses these levels when assessing skills, overall fit, strengths, and risks.

The optional live proficiency evaluation compares three otherwise identical n8n
profiles against the real model. It requires a configured server key and consumes
API credits; it is skipped during ordinary test runs:

```bash
FITCHECK_RUN_LIVE_EVAL=1 node --env-file=.env.local node_modules/vitest/vitest.mjs run lib/analysis/skill-levels.live.test.ts
```

## Deployment

Deploy the Next.js application to a runtime that supports route handlers. Configure server-only `OPEN_AI_KEY`, exact `OPEN_AI_MODEL=gpt-6-luna`, and `ALLOWED_ORIGINS` with the production website origin, for example `https://fitcheck.example.com`.

For the durable backend, configure the same `OPEN_AI_MODEL=gpt-6-luna` on API and worker. The API admission registry needs only the model; supply `OPEN_AI_KEY` only to the website and worker through server secret storage. Follow the rollout record before pushing provider changes: disable all three autodeploy switches, stop new backend admission, drain old frozen jobs, migrate and deploy the compatible API/worker before reopening admission and deploying the website.

The login is intentionally local-only for product testing: there is no email confirmation, remote session, cross-device synchronization, subscription, or website account database. Clearing browser site data removes local FitCheck data. Use the profile page's **Delete local account** action to remove one account and all of its associated local data.


Optional website telemetry uses `METRICS_BACKEND_URL` (a fixed HTTPS backend origin), `METRICS_BRIDGE_KEY` (matching backend ingestion credentials), `METRICS_COOKIE_SECRET` (a separate high-entropy signing secret), and explicit `METRICS_ENVIRONMENT=development|production|test`. Configure these server-side only, alongside the exact website origin in `ALLOWED_ORIGINS`; never prefix these secrets with `NEXT_PUBLIC_`. The deployed development services still use production builds: keep their telemetry partition `development`. Backend collection must be enabled separately with the matching environment and key. Missing cookie signing configuration disables website collection safely.

The bridge uses a 1500 ms deadline, refuses redirects, and returns safe delivery results on outages. Local HTTP requires `METRICS_ALLOW_LOCAL_HTTP=true`, a non-production runtime, and a loopback backend origin. The visitor cookie is HttpOnly, SameSite=Lax, Secure in production builds, and expires 180 days after its original issuance without sliding renewal. Browser observations stay in memory (100 events, batches of 20 and 32 KiB, two retries); the deletion boundary rotates visitor/session identity and requests deletion of that visitor’s telemetry even when remote delivery fails. These boundaries are available for UI instrumentation; they do not connect local accounts to backend identities.

Telemetry setup, formulas, operator reports, retention, and limitations are documented
in [backend metrics operations](backend/README.md#telemetry-and-operator-reports).
The [metrics development rollout record](docs/deployments/2026-10-14-fitcheck-metrics.md)
preserves the previous deployment evidence. The separate
[OpenAI rollout record](docs/deployments/2026-10-14-fitcheck-openai.md) tracks the
matched website/API/worker transition and its pending external checks. Local
implementation and mock tests do not establish live account/model access; paid
tests require a concrete approved spend cap.

`METRICS_CAMPAIGN_CODES` is a comma-separated allowlist of public dimension codes;
mirror it in backend `FITCHECK_METRICS_CAMPAIGN_CODES` as a JSON array. Arbitrary UTM
values are discarded into `other`; absent campaigns use `direct`. All `METRICS_*`
configuration stays server-side, with only enabled state and validated public codes
passed to the browser. The `/` page is prerendered: supply configuration at build
time and rebuild/redeploy after changing enabled state or campaign codes. A runtime
reload alone does not refresh these public props.

Telemetry counts browser visitors, not authenticated website accounts: a shared
browser can contain several local accounts; another device, cookie expiry, clearing
site data, or deletion creates a different visitor. No email/password, profile/task
text, full URL, raw UTM, or IP identity enters the event registry. Backend account
metrics form a separate population until explicit authenticated linking exists.
To disable collection, remove the website bridge configuration and rebuild/deploy,
and set backend `FITCHECK_METRICS_ENABLED=false` on API and worker. Preserve domain
and accounting data and additive migrations; see the rollout record for rollback.

Guest sessions, successful-operation quotas and durable worker spending ceilings
(ANY-651) are documented in [backend/README.md](backend/README.md#guest-sessions-and-quotas-any-651).
Migration 0008 requires coordinated API/worker rollout; guest admission defaults off.
