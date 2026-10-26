# FitCheck Website — Design Specification

> **Scope update — 2026-10-12:** The user chose FitCheck as a website-only product and authorized removal of the extension code, builds, and authentication. This document is a historical implementation record; completed steps, test results, and migration history remain evidence of the work at that time. Extension steps and compatibility requirements are superseded and must not be executed or restored. Future work uses website cookie sessions with web-origin CSRF, website IndexedDB as the legacy import source, independent same-account sessions across devices, and website/backend CI. See the current backend foundation, storage, and authentication specifications.

## Purpose

Turn the existing FitCheck popup-style preview into a testable web product. A potential customer must be able to create a local account, define a real freelancer profile, submit a real vacancy as text or a public URL, receive a real LLM analysis, revisit previous results, and switch the interface between Russian and English.

The website is the only supported product surface for this iteration. The existing extension code may remain in the repository, but it is not part of the primary user journey or the acceptance criteria.

## Product Principles

- The product must demonstrate real analysis rather than substitute mock results.
- The backend is stateless and limited to capabilities that cannot safely or reliably run in the browser.
- User data remains in the current browser through IndexedDB.
- Every core flow is usable on desktop and mobile, while desktop is the primary presentation format.
- Failed extraction or analysis never discards the user's input.
- The interface must accurately describe local-only login and avoid implying server-side account security or cross-device sync.

## Success Criteria

- A new visitor can create a local account with name, email, and password, then remain signed in after a page reload.
- A returning local user can sign in with the saved email and password.
- The user can create and edit a freelancer profile without relying on the sample profile.
- The user can enter a vacancy either by pasting its contents or by supplying any public HTTP or HTTPS URL.
- URL extraction returns an editable vacancy draft, or falls back to manual entry with a useful error.
- A valid vacancy and profile produce a real, schema-validated OpenRouter analysis.
- The user can return to the vacancy-source screen from review and result screens.
- Completed analyses remain available in local history after a reload.
- A visible RU/EN switch changes the interface immediately and persists per local user.
- The website uses the available viewport and no longer resembles a 400 by 600 pixel browser-extension popup.
- Automated tests, type checking, linting, and the Next.js production build pass.

## Architecture

FitCheck uses a client-first Next.js architecture with three boundaries:

1. The Next.js website owns routing, responsive pages, the product workflow, and calls to server endpoints.
2. A versioned IndexedDB repository owns local users, sessions, profiles, preferences, vacancy drafts, history, and feedback.
3. Stateless Next.js route handlers provide public-page extraction and OpenRouter analysis. They do not persist user data.

The OpenRouter API key remains server-only. The browser sends only the profile, current vacancy, selected locale, and up to ten compact calibration entries required for the current analysis.

The website must not use `lib/mock-data.ts` or the preview runtime in its production path. Mock objects remain valid only as explicit test fixtures. The extension entrypoints and Chrome storage implementation are outside this iteration and do not constrain the website layout or local storage schema.

Before implementation, the relevant Next.js 16.3 documentation under `node_modules/next/dist/docs/` must be read for App Router pages, route handlers, and server-side networking because this repository's `AGENTS.md` warns that framework APIs and conventions differ from prior versions.

## Routes and Screens

### Local Authentication

The unauthenticated route presents one page with two modes:

- **Create local account:** name, email, and password.
- **Sign in:** email and password.

Creating an account normalizes the email, rejects a duplicate local email, hashes the password with a unique salt using Web Crypto, creates the active local session, and routes to the product. Signing in compares the derived password hash without sending credentials to the server.

The page states that the account exists only in this browser and is not synchronized between devices. Email verification, password recovery, OAuth, server sessions, and remote accounts are explicit non-goals.

### Application Shell

Authenticated pages share a responsive application shell:

- FitCheck brand and concise value proposition;
- navigation for New Analysis, History, and Profile;
- a persistent RU/EN selector;
- the current user's name and a sign-out action.

Desktop layouts use the available width with readable content constraints and optional side panels. Mobile layouts collapse navigation without changing product capabilities.

### Profile Setup and Editing

A user without a complete profile is guided to create one before analysis. The profile contains specialization, skills, years of experience, preferred hourly rate, and English level. The form starts empty for a real user; sample data may be offered only as an explicit user action and must be visibly labeled.

Saving the profile returns the user to New Analysis. Editing a profile affects future analyses and does not rewrite prior history snapshots.

### New Analysis: Source Selection

New Analysis begins on a stable first step with two visible source modes:

- **From URL:** accepts any public HTTP or HTTPS vacancy page.
- **Paste text:** accepts a title plus vacancy description, with optional skills, budget, and source URL.

Changing modes does not silently erase data from the other mode. The user explicitly submits the selected source to continue.

### Vacancy Review

Successful URL extraction and valid manual input lead to the same editable vacancy-review screen. The user can correct the title, description, skills, budget, and source URL before analysis.

This screen always includes a clear **Back to vacancy selection** action. Going back preserves the current draft so the user can switch input method or correct the source.

### Analysis and Result

Submitting the review screen calls the real analysis endpoint and shows meaningful progress. The validated result includes:

- Fit Score from 0 to 100;
- deterministic GO for scores of at least 70 and NO-GO below 70;
- localized label and summary;
- exactly three strengths;
- zero to three risks;
- breakdown scores for skills, experience, rate, English, and requirements.

The result page provides **Back to vacancy selection**, **Analyze another vacancy**, detailed breakdown, and score-correction actions. Starting another analysis resets the current workflow only after the completed result has been persisted.

### History

History lists completed analyses newest first and allows reopening the full result. Each entry preserves the profile and vacancy snapshots used for that analysis so later profile edits do not alter old results. A failed or incomplete analysis never creates a history item.

History can be cleared only after explicit confirmation. The initial storage limit is 50 completed analyses per local user; the newest ten feedback-bearing summaries may be used as calibration memory.

### Profile and Local Account Management

The Profile area edits freelancer details and displays local-account information. Signing out clears only the active session. Deleting the local account requires explicit confirmation and removes that user's profile, drafts, history, feedback, preferences, and credentials from IndexedDB.

## IndexedDB Data Model

IndexedDB uses a versioned schema and repository interface rather than direct database calls from React components. The minimum logical records are:

- `LocalUser`: id, normalized email, display name, password salt, password hash, and creation timestamp.
- `LocalSession`: active user id and creation timestamp.
- `UserPreferences`: user id and locale.
- `FreelancerProfile`: user id, profile fields, and update timestamp.
- `VacancyDraft`: user id, source mode, raw source, editable normalized fields, and update timestamp.
- `HistoryEntry`: user id, vacancy snapshot, profile snapshot, original analysis, optional correction, and creation timestamp.

Every user-owned record is keyed or indexed by `userId`. Database upgrades preserve valid data and default newly introduced optional fields. Repository methods expose domain operations such as create user, authenticate, load active session, save profile, save draft, add analysis, and delete user data.

The password is stored only as a salted derived hash. This reduces accidental disclosure but does not make a browser-local account equivalent to secure server authentication. The product copy and documentation must retain that distinction.

## Vacancy Extraction Endpoint

`POST /api/extract` accepts one URL and returns an editable normalized draft containing a title, main description, discovered skills when possible, optional budget, and canonical source URL.

The endpoint is best-effort. It supports public HTML or plain-text pages but does not promise access to authenticated pages, anti-bot protected pages, or content rendered only after complex client-side execution. In those cases it returns a stable error that directs the user to manual paste.

### Network Safety

Because the endpoint accepts arbitrary URLs, it must defend against server-side request forgery:

- allow only HTTP and HTTPS;
- reject embedded credentials and malformed hosts;
- resolve hostnames and reject loopback, link-local, private, reserved, and metadata-network addresses;
- apply the same validation to every redirect target;
- limit redirect count, connection time, total time, and response bytes;
- accept only supported HTML and text content types;
- never forward browser cookies, authorization headers, or user-provided headers.

Extraction removes scripts, styles, navigation, forms, and repeated boilerplate. The returned description has an explicit length limit. Remote page text is untrusted content and must never be treated as system or developer instructions in the LLM prompt.

## Analysis Endpoint

The existing `/api/analyze` domain contract remains the basis of real analysis. The website supplies the active profile, reviewed vacancy, locale, and at most ten compact calibration entries.

The server validates request size and every field, constructs a prompt that clearly delimits untrusted vacancy text, calls OpenRouter with a server-only key, validates structured output, and normalizes the verdict from the numeric score. The endpoint stores nothing.

Production never falls back to a mock analysis. If `OPENROUTER_API_KEY` is missing or the provider is unavailable, the user receives a localized, retryable configuration or provider error.

The origin policy must support the deployed website origin and local development. It remains defense in depth rather than user authentication.

## Localization

All user-visible application copy comes from typed RU and EN dictionaries. A visible language selector is available on authentication and authenticated screens.

On a user's first visit, the initial locale follows the browser language when it begins with `ru`; otherwise it is English. An unauthenticated choice is retained locally. After account creation or sign-in, the selected locale is stored in that user's preferences and controls both interface copy and the requested LLM output language.

Switching language takes effect immediately without losing form input or changing the current workflow step. Dates and numeric presentation use the active locale.

## Error Handling

Errors are typed and translated into actionable UI states:

- duplicate local email, unknown email, or incorrect password;
- incomplete or invalid freelancer profile;
- malformed, blocked, private, unsupported, too large, or timed-out vacancy URL;
- insufficient extracted text with manual-paste fallback;
- empty, invalid, or oversized manual vacancy;
- network failure, OpenRouter rate limit, timeout, missing server configuration, invalid model output, or unknown upstream error;
- unavailable or incompatible IndexedDB storage.

All recoverable failures preserve the current form and draft. Extraction errors keep the URL and expose manual paste. Analysis errors keep the reviewed vacancy and expose retry. Existing local data remains readable when either server endpoint fails.

## Testing Strategy

Implementation follows red-green-refactor TDD.

### Unit and Repository Tests

- email normalization, password derivation and comparison, duplicate handling, session restoration, sign-out, and account deletion;
- IndexedDB schema creation, version upgrades, per-user isolation, draft persistence, history limits, and calibration-memory limits;
- locale detection, manual switching, and per-user persistence;
- vacancy validation, normalization, verdict normalization, and prompt construction.

### API Tests

- extraction of representative static HTML and text fixtures;
- rejection of invalid schemes, credentials, private and reserved addresses, unsafe redirects, unsupported content, oversized responses, and timeouts;
- analysis request validation and stable error mapping while replacing only the external OpenRouter transport;
- prompt-injection boundaries and structured-output validation.

### Component and Flow Tests

- local account creation, login failure, successful return login, session restoration, and sign-out;
- required profile setup and profile editing;
- text input, URL input, editable vacancy review, and preserved back navigation;
- successful analysis, retryable failure, history creation only on success, reopening history, and feedback correction;
- immediate RU/EN switching without state loss;
- desktop navigation and mobile navigation behavior.

### Manual Acceptance

With a real `OPENROUTER_API_KEY` configured:

1. Create a local user and profile.
2. Paste a real vacancy and receive a real result.
3. Return to source selection without losing the completed history entry.
4. Import a public vacancy URL, edit the extracted draft, and analyze it.
5. Confirm that a blocked URL offers manual paste rather than a dead end.
6. Reopen both results from history.
7. Reload the site and confirm that session, profile, language, drafts, and history persist.
8. Switch between RU and EN on an in-progress form without losing input.
9. Sign out, sign back in, and confirm the same local data is available.
10. Verify desktop and mobile viewport layouts.

Final verification runs the full test suite, TypeScript checking, ESLint, and a Next.js production build.

## Configuration

The deployed server requires:

- `OPENROUTER_API_KEY`;
- `OPENROUTER_MODEL`, defaulting to the documented project model;
- an origin configuration appropriate to the deployed website and local development.

No public environment variable may contain the OpenRouter key. The README must describe the local-only nature of accounts, the URL extraction limitations, and the real-analysis setup.

## Explicit Non-Goals

- Chrome-extension product flows or extension packaging changes.
- Server-side user accounts, a server database, email verification, password recovery, OAuth, or cross-device synchronization.
- Billing, subscriptions, quotas, analytics, or admin tools.
- Guaranteed extraction of authenticated, anti-bot protected, or JavaScript-only pages.
- Browser automation for logging into job platforms.
- Automatic proposal generation or submission.
- Additional interface languages beyond Russian and English.
