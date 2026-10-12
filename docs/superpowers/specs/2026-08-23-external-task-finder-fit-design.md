# External Task Finder & Fit — Design Specification

> **Scope update — 2026-10-12:** The user chose FitCheck as a website-only product and authorized removal of the extension code, builds, and authentication. This document is a historical implementation record; completed steps, test results, and migration history remain evidence of the work at that time. Extension steps and compatibility requirements are superseded and must not be executed or restored. Future work uses website cookie sessions with web-origin CSRF, website IndexedDB as the legacy import source, independent same-account sessions across devices, and website/backend CI. See the current backend foundation, storage, and authentication specifications.

## Purpose

Build an installable Chrome Extension that helps non-native English-speaking Upwork freelancers decide in under a minute whether a job is worth spending connects on. The extension reads the current Upwork job page, compares it with a locally stored freelancer profile, and returns a personalized Fit Score, explanation, strengths, risks, and a GO or NO-GO verdict.

The MVP supports Upwork only. Fiverr and other marketplaces are outside this scope.

## Success Criteria

- A first-time user can complete a local profile containing specialization, skills, experience, preferred hourly rate, and English level.
- On a supported Upwork job page, the extension extracts the available job title, description, skills, budget or hourly range, experience level, posting age, and client information.
- A user can request an analysis and receive a validated result in less than 60 seconds under normal API conditions.
- The result contains a score from 0 to 100, a deterministic GO or NO-GO verdict, a concise explanation, exactly three strengths, zero to three risks, and a five-category breakdown.
- The user can correct an inaccurate score and save a calibration note for later analyses.
- Profile, history, and feedback remain in extension-local storage. Only the request required for analysis is sent to the backend.
- The popup and generated analysis use Russian when the system UI locale begins with `ru`; otherwise they use English.
- The project passes unit tests, component tests, type checking, linting, the Next.js production build, and the WXT production build.

## Architecture

The repository contains two runtime surfaces that share domain types and React UI components:

1. A WXT-powered React Chrome Extension targeting Manifest V3. It owns the popup, the Upwork content script, Chrome messaging, browser actions, and `chrome.storage.local` persistence.
2. The existing Next.js 16 application. It provides a browser-based preview of the shared UI and a server-only `POST /api/analyze` route that calls OpenRouter.

The extension never receives `OPENROUTER_API_KEY`. It calls the deployed Next.js backend using `WXT_PUBLIC_API_BASE_URL`. The backend reads `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, calls the OpenRouter Chat Completions API with Structured Outputs, validates the model result, and returns only the analysis JSON.

## Main Components

### Extension Entrypoints

- `entrypoints/popup/` mounts the shared React application into a fixed-width popup and selects the Chrome runtime adapter.
- `entrypoints/upwork.content.ts` runs only on supported Upwork URLs in the isolated world. It extracts the current job and responds to popup messages.
- `wxt.config.ts` defines Manifest V3 metadata, permissions, host access, content security policy, icons, and English/Russian manifest localization.

WXT is used instead of hand-maintained multi-entry Vite configuration because its entrypoint conventions generate the manifest and correctly package popup and content-script bundles while preserving a normal React development workflow.

### Shared Application UI

`components/extension/extension-app.tsx` owns the user-visible state machine:

- onboarding;
- ready to analyze;
- loading;
- result;
- detailed breakdown;
- feedback correction;
- history;
- profile;
- unsupported page;
- recoverable error.

The current page-level state in `app/page.tsx` moves into this shared component. Environment-specific behavior is injected through a small runtime interface so the same UI can use Chrome APIs in the popup and deterministic data in the Next.js preview. Preview-only scenario controls are never rendered inside the production extension.

### Upwork Parser

The parser is a pure function over a `Document` plus the page URL. It returns either a normalized `Job` or a typed unsupported/incomplete result. It uses narrow, ordered extraction strategies:

1. stable structured data present on the page, when available;
2. semantic selectors and accessible labels;
3. conservative text fallbacks for optional fields.

The parser does not fabricate missing budget, rating, or experience data. Missing optional fields remain absent and are disclosed to the model. The title and meaningful description are required; without them the popup shows an incomplete-data error rather than sending a low-quality request.

### Local Storage

The storage adapter persists one versioned object in `chrome.storage.local` containing:

- the current freelancer profile;
- at most 50 history entries, newest first;
- feedback attached to the relevant history entry;
- the schema version.

Only the latest 10 history entries and their feedback are used as calibration memory in an analysis request. The profile screen can reset the profile. The history screen can clear all history after explicit confirmation. Storage migrations default missing fields without deleting valid user data.

### Localization

Runtime locale resolution checks `chrome.i18n.getUILanguage()` in the extension and `navigator.language` in preview. Locales beginning with `ru` resolve to `ru`; every other locale resolves to `en`. There is no manual locale switch in the MVP.

All interface copy comes from typed dictionaries. The backend receives the resolved locale and instructs the model to write every user-visible analysis field in that language. Technical enum values and property names remain language-independent.

### Analysis Backend

`POST /api/analyze` accepts a JSON request containing:

- normalized freelancer profile;
- normalized current job;
- up to 10 compact history/calibration entries;
- `ru` or `en` locale.

The route rejects malformed JSON, unsupported origins, oversized fields, invalid numeric ranges, and more than 10 memory items. Validation is shared between the route and client through explicit TypeScript schemas.

The model prompt follows the product plan:

- SYSTEM: freelancer specialization, rate, experience, skills, English limitations, scoring rules, and output language;
- CONTEXT: current job content and explicitly marked missing fields;
- TASK: assess fit and return score, explanation, strengths, risks, and breakdown;
- MEMORY: recent analyses and user corrections used only for calibration.

The server uses the OpenRouter Chat Completions API with a strict JSON Schema. The default model is `openrouter/free`; `OPENROUTER_MODEL` can override it. A refusal, incomplete response, schema violation, timeout, or upstream error is converted to a stable application error without exposing secrets or raw provider output.

The server normalizes the verdict after validation: scores of 70 or greater are `GO`; lower scores are `NO_GO`. This prevents disagreement between the numeric score and verdict.

## User Flows

### First Run

1. The popup resolves the system locale and loads extension storage.
2. If no profile exists, localized onboarding is displayed.
3. The user enters specialization, at least one skill, experience years from 0 to 60, preferred hourly rate from 0 to 1000, and English level.
4. A valid profile is stored locally and the popup proceeds to page detection.

### Analyze Current Job

1. The popup queries the active tab and asks the content script for the current normalized job.
2. An unsupported URL produces the localized “Open an Upwork job” state.
3. Missing required page data produces an incomplete-data error with Retry.
4. A valid job is shown to the user before analysis.
5. Analyze sends the profile, job, locale, and latest calibration memory to the backend.
6. A successful response is added to history and displayed.
7. A failed response is not added to history and can be retried.

### Act on a Result

- For `GO`, “Apply on Upwork” activates the source tab and asks the content script to scroll to the proposal/application action when it can be found.
- For `NO_GO`, “Skip Job” closes the popup and does not modify the Upwork page.
- “View details” opens the five-category score breakdown.
- “Not accurate?” opens feedback correction.

### Correct an Analysis

1. The user chooses a corrected score from 0 to 100 and may enter a note up to 500 characters.
2. Saving updates the corresponding local history entry.
3. The corrected score and note are included in later calibration memory.
4. The original model result remains preserved alongside the correction so the system can distinguish prediction from feedback.

### Manage History and Profile

- History lists up to 50 local entries and can reopen a result.
- Clear history requires explicit confirmation.
- Saving profile changes affects future analyses only.
- Reset profile requires confirmation and returns to onboarding without silently deleting history.

## Data Contracts

`FreelancerProfile` contains specialization, skills, experience years, preferred hourly rate, and English level.

`Job` contains a stable URL-derived identifier, source URL, title, description, skills, optional hourly or fixed budget values, optional experience level, optional posting age, and optional client rating and spend information.

`FitAnalysis` contains score, normalized status, localized label, localized summary, exactly three localized strengths, zero to three localized risks, and integer breakdown scores from 0 to 100 for skills, experience, rate, English, and requirements.

`AnalysisFeedback` contains corrected score, optional note, and creation timestamp.

`HistoryEntry` contains the normalized job snapshot, original analysis, optional feedback, and creation timestamp.

## Permissions and Security

The extension requests only:

- `storage` for local profile, history, and feedback;
- `activeTab` to coordinate with the active Upwork page;
- the minimum Upwork match patterns required by the content script;
- the backend origin required for analysis requests.

The extension includes no remote executable code. The OpenRouter key is read only in the server runtime. Error responses and logs never include the key, full prompt, profile, or raw model output.

The backend checks the request `Origin` against the comma-separated `ALLOWED_ORIGINS` environment variable. Local development origins are opt-in rather than enabled in production automatically. Request bodies and every free-text field have explicit size limits. This origin check limits accidental browser access but is not treated as user authentication; production monetization and account-level quotas are outside the MVP.

## Error Handling

The client maps failures to localized stable categories:

- unsupported Upwork page;
- required job data unavailable;
- profile unavailable or invalid;
- network or backend unavailable;
- OpenRouter rate limit;
- OpenRouter timeout or incomplete response;
- invalid model output;
- unknown recoverable error.

Retry repeats page extraction before sending another analysis request. No history entry is created until a complete validated analysis is available. Existing local data remains readable when analysis fails.

## Testing Strategy

Implementation follows red-green-refactor TDD.

- Parser unit tests use sanitized static HTML fixtures for complete, partial, unsupported, and changed-selector pages.
- Domain tests cover validation boundaries, verdict normalization, memory truncation, storage migration, localization selection, and prompt construction.
- Storage adapter tests exercise real serialization behavior against an in-memory implementation of the Chrome storage contract.
- React Testing Library tests cover onboarding, supported and unsupported pages, loading, GO and NO-GO results, feedback saving, history clearing, profile reset, and Russian/English copy.
- Route-handler tests exercise real request validation and response mapping while replacing only the external OpenRouter transport.
- Build verification runs TypeScript with no ignored build errors, ESLint, the complete test suite, `next build`, and `wxt build`.
- Manual verification loads `.output/chrome-mv3` as an unpacked extension, tests Russian and English browser locales, and checks a supported Upwork job page plus a non-Upwork page.

## Configuration and Developer Experience

`.env.example` documents:

- `OPENROUTER_API_KEY` for the Next.js server;
- `OPENROUTER_MODEL=openrouter/free` as the default model;
- `ALLOWED_ORIGINS` for deployed extension and local preview origins;
- `WXT_PUBLIC_API_BASE_URL` for the extension build.

Package scripts provide separate commands for Next.js development, extension development, complete tests, both production builds, and extension zip packaging. The WXT artifact is emitted to `.output/chrome-mv3` and can be loaded through Chrome’s “Load unpacked” flow.

`next.config.mjs` no longer ignores TypeScript build errors.

## Explicit Non-Goals

- Fiverr or other marketplace parsing.
- User accounts, subscriptions, billing, or cloud profile synchronization.
- Chrome Web Store submission automation.
- Proposal generation or automatic proposal submission.
- Upwork private API integration.
- Analytics/Amplitude integration.
- PDF profile reports or other viral artifacts.
- Manual language selection.
- Guaranteed protection of an unauthenticated public endpoint from determined abuse.
