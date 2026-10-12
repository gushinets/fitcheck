# FitCheck

FitCheck is a bilingual service for checking whether a freelance task fits a freelancer profile. A user can load any public task URL or paste its text, review the extracted details, and send the task to an LLM for a Fit Score, strengths, risks, and a GO / NO-GO recommendation. The flow is designed for repeated use throughout the day while browsing new tasks.

The website supports English and Russian with a manual RU / EN switch. Local accounts, profiles, drafts, analysis history, and score corrections are stored in IndexedDB in the current browser. The server receives only the current extraction or analysis request and does not persist user data.

## Requirements

- Node.js 22 or newer
- pnpm 10
- A DeepSeek API key with available balance

## Install and configure

```bash
pnpm install
cp .env.example .env.local
```

Set the server-side key in `.env.local`:

```dotenv
DEEPSEEK_API_KEY=your_server_side_key
DEEPSEEK_MODEL=deepseek-v4-flash
ALLOWED_ORIGINS=http://localhost:3000
```

Never expose `DEEPSEEK_API_KEY` in a public environment variable or client-side source. FitCheck defaults to `deepseek-v4-flash`; set `DEEPSEEK_MODEL` only when intentionally changing the server-side analysis model.

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

Deploy the Next.js application to a runtime that supports route handlers. Configure `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, and `ALLOWED_ORIGINS` with the production website origin, for example `https://fitcheck.example.com`.

The login is intentionally local-only for product testing: there is no email confirmation, remote session, cross-device synchronization, subscription, or server database. Clearing browser site data removes local FitCheck data. Use the profile page's **Delete local account** action to remove one account and all of its associated local data.
