# FitCheck

FitCheck is a Manifest V3 Chrome Extension that reads the active Upwork job, compares it with a locally stored freelancer profile, and returns an OpenRouter-powered Fit Score with strengths, risks, and a GO or NO-GO verdict.

The extension supports Upwork only. The UI and generated analysis use Russian when Chrome's system UI locale starts with `ru`; every other locale uses English.

## Requirements

- Node.js 22 or newer
- pnpm 10
- Google Chrome
- An OpenRouter API key

## Install

```bash
pnpm install
```

Copy `.env.example` to `.env.local` and set:

```dotenv
OPENROUTER_API_KEY=your_server_side_key
OPENROUTER_MODEL=openrouter/free
ALLOWED_ORIGINS=chrome-extension://YOUR_EXTENSION_ID,http://localhost:3000
WXT_PUBLIC_API_BASE_URL=http://localhost:3000
```

`OPENROUTER_API_KEY` is used only by the Next.js server. Never put it in a `WXT_PUBLIC_*` variable or extension source. The default `openrouter/free` router selects a currently available free model that supports the request.

## Run locally

Start the Next.js backend and browser preview:

```bash
pnpm dev
```

In another terminal, start the extension development build:

```bash
pnpm dev:extension
```

WXT can launch a development browser automatically. To load a production-style unpacked build manually:

1. Run `pnpm build:extension`.
2. Open `chrome://extensions`.
3. Enable Developer mode.
4. Click **Load unpacked** and select `.output/chrome-mv3`.
5. Copy the generated extension ID.
6. Replace `YOUR_EXTENSION_ID` in `ALLOWED_ORIGINS` and restart the Next.js server.
7. Open an Upwork job page and click FitCheck.

The extension stores the freelancer profile, up to 50 analyses, and score corrections in `chrome.storage.local`. The backend receives only the current analysis request and does not persist it. The latest 10 local analyses may be included as calibration memory.

## Verify and package

```bash
pnpm test
pnpm typecheck
pnpm lint
pnpm build:web
pnpm build:extension
pnpm zip:extension
```

The unpacked extension is written to `.output/chrome-mv3`. WXT writes the zip archive under `.output`.

## Backend deployment

Deploy the Next.js application to a server that supports route handlers, set `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and the production `ALLOWED_ORIGINS`, then build the extension with `WXT_PUBLIC_API_BASE_URL` pointing at that HTTPS deployment.

Origin checking limits accidental browser access but is not user authentication. The MVP does not include accounts, subscriptions, per-user quotas, or protection against determined abuse of a public endpoint.
