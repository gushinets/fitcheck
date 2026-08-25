# FitCheck

FitCheck is a bilingual website for testing whether a real vacancy fits a freelancer profile. A user can load any public vacancy URL or paste its text, review the extracted details, and send the vacancy to an LLM for a Fit Score, strengths, risks, and a GO / NO-GO recommendation.

The website supports English and Russian with a manual RU / EN switch. Local accounts, profiles, drafts, analysis history, and score corrections are stored in IndexedDB in the current browser. The server receives only the current extraction or analysis request and does not persist user data.

## Requirements

- Node.js 22 or newer
- pnpm 10
- An OpenRouter API key

## Install and configure

```bash
pnpm install
cp .env.example .env.local
```

Set the server-side key in `.env.local`:

```dotenv
OPENROUTER_API_KEY=your_server_side_key
OPENROUTER_MODEL=openrouter/free
ALLOWED_ORIGINS=http://localhost:3000
```

Never expose `OPENROUTER_API_KEY` in a public environment variable or client-side source. `openrouter/free` asks OpenRouter to select a currently available free model compatible with the request; set a specific model when predictable output is more important.

## Run the website

```bash
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000), create a local account, complete the freelancer profile, and add a real vacancy.

URL import is best-effort. FitCheck accepts arbitrary public HTTP(S) pages, blocks private/internal network addresses, limits redirects and response size, and extracts readable vacancy content. Pages that require authentication, execute content only in the browser, or block automated requests may not load; paste the vacancy text manually in that case.

## Verify

```bash
pnpm test
pnpm typecheck
pnpm lint
pnpm build:web
```

## Deployment

Deploy the Next.js application to a runtime that supports route handlers. Configure `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and `ALLOWED_ORIGINS` with the production website origin, for example `https://fitcheck.example.com`.

The login is intentionally local-only for product testing: there is no email confirmation, remote session, cross-device synchronization, subscription, or server database. Clearing browser site data removes local FitCheck data. Use the profile page's **Delete local account** action to remove one account and all of its associated local data.

The legacy Chrome extension source remains in the repository but is not part of the current website product flow.
