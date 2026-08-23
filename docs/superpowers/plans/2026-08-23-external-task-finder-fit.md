# External Task Finder & Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing FitCheck Next.js prototype into an installable Manifest V3 Chrome Extension for Upwork with local profile/history storage and a secure OpenRouter-backed fit-analysis endpoint.

**Architecture:** A WXT React popup and Upwork content script share domain code and UI components with the existing Next.js preview. The extension stores user data in `chrome.storage.local` and calls a Next.js route handler, which validates requests and uses the OpenRouter Chat Completions API with strict Structured Outputs.

**Tech Stack:** Next.js 16.3, React 19, TypeScript 5.7, Tailwind CSS 4, WXT 0.21, OpenAI-compatible JavaScript SDK, OpenRouter API, Zod, Vitest, jsdom, React Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-23-external-task-finder-fit-design.md`

## Global Constraints

- Support Chrome Manifest V3 and Upwork pages only.
- Store profile, at most 50 history entries, and feedback in `chrome.storage.local`.
- Send at most 10 recent history/calibration entries to the backend.
- Resolve `ru` for system locales beginning with `ru`; otherwise resolve `en`.
- Keep `OPENROUTER_API_KEY` server-only and call the OpenRouter Chat Completions API.
- Default to `openrouter/free`, overridable through `OPENROUTER_MODEL`.
- Normalize score `>= 70` to `GO`, otherwise `NO_GO`.
- Do not ignore TypeScript build errors.
- This workspace has no Git repository; commit steps are intentionally omitted because `git commit` cannot run.

---

### Task 1: Test and Extension Build Foundation

**Files:**
- Modify: `package.json`
- Modify: `next.config.mjs`
- Modify: `tsconfig.json`
- Create: `vitest.config.ts`
- Create: `vitest.setup.ts`
- Create: `wxt.config.ts`
- Create: `.env.example`
- Create: `public/_locales/en/messages.json`
- Create: `public/_locales/ru/messages.json`

**Interfaces:**
- Consumes: existing Next.js application and shared `@/*` path alias.
- Produces: `pnpm test`, `pnpm typecheck`, `pnpm build:web`, `pnpm build:extension`, and `pnpm zip:extension` commands; WXT React compilation and Vitest/jsdom execution.

- [ ] **Step 1: Add dependencies and scripts**

Add runtime dependencies `openai` and `zod`; add dev dependencies `wxt`, `@wxt-dev/module-react`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, and `@testing-library/user-event`. Define scripts:

```json
{
  "dev": "next dev",
  "dev:extension": "wxt",
  "test": "vitest run --passWithNoTests",
  "test:watch": "vitest",
  "typecheck": "tsc --noEmit",
  "build": "pnpm build:web && pnpm build:extension",
  "build:web": "next build",
  "build:extension": "wxt build",
  "zip:extension": "wxt zip",
  "lint": "eslint ."
}
```

- [ ] **Step 2: Install the updated dependency graph**

Run: `pnpm install`

Expected: exit 0 and `pnpm-lock.yaml` updated with the exact resolved packages.

- [ ] **Step 3: Configure Vitest and WXT**

Use Vitest with jsdom. Add WXT's Vitest plugin after the first entrypoint exists in Task 9, because WXT 0.21 rejects preparation when the project has no entrypoints:

```ts
// vitest.config.ts
import { defineConfig } from "vitest/config"

export default defineConfig({
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"] },
})
```

Configure WXT with `@wxt-dev/module-react`, `storage` and `activeTab`, localized manifest name/description, icons, and a host permission derived from `WXT_PUBLIC_API_BASE_URL`. Keep Upwork page access on the content-script match patterns rather than a broad all-sites permission.

- [ ] **Step 4: Enable strict production type checking**

Remove `typescript.ignoreBuildErrors` from `next.config.mjs`. Add WXT-generated types to `tsconfig.json` only through WXT's generated `.wxt/tsconfig.json` integration, preserving Next.js plugin settings.

- [ ] **Step 5: Verify the foundation**

Run: `pnpm typecheck`

Expected: exit 0 before feature code is added.

Run: `pnpm test`

Expected: exit 0 with Vitest reporting no test files or the configured pass-with-no-tests behavior.

---

### Task 2: Domain Contracts, Validation, and Localization

**Files:**
- Modify: `lib/types.ts`
- Create: `lib/analysis/schema.ts`
- Create: `lib/analysis/normalize.ts`
- Create: `lib/i18n/messages.ts`
- Create: `lib/i18n/locale.ts`
- Create: `lib/analysis/schema.test.ts`
- Create: `lib/i18n/locale.test.ts`

**Interfaces:**
- Consumes: Zod.
- Produces: `Locale = "en" | "ru"`, `AnalysisRequest`, `AnalysisFeedback`, enriched `Job` and `HistoryEntry`, `analysisRequestSchema`, `fitAnalysisSchema`, `normalizeAnalysis()`, `resolveLocale()`, and typed `messages`.

- [ ] **Step 1: Write failing contract tests**

Cover at least these behaviors:

```ts
it("rejects more than ten memory entries", () => {
  const result = analysisRequestSchema.safeParse({
    profile: validProfile,
    job: validJob,
    locale: "en",
    memory: Array.from({ length: 11 }, () => validMemory),
  })
  expect(result.success).toBe(false)
})

it("normalizes a score of seventy to GO", () => {
  expect(normalizeAnalysis({ ...validAnalysis, score: 70, status: "NO_GO" }).status)
    .toBe("GO")
})

it.each([["ru-RU", "ru"], ["ru", "ru"], ["en-US", "en"], ["es", "en"]])(
  "maps %s to %s",
  (system, expected) => expect(resolveLocale(system)).toBe(expected),
)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pnpm vitest run lib/analysis/schema.test.ts lib/i18n/locale.test.ts`

Expected: FAIL because schemas and locale helpers do not exist.

- [ ] **Step 3: Implement minimal domain contracts**

Extend `Job` with `url`, optional fixed budget, client rating, and client spend. Extend history with ISO `createdAt` and optional feedback. Validate:

```ts
export const fitAnalysisSchema = z.object({
  score: z.number().int().min(0).max(100),
  status: z.enum(["GO", "NO_GO"]),
  label: z.string().min(1).max(80),
  summary: z.string().min(1).max(800),
  strengths: z.array(z.string().min(1).max(240)).length(3),
  risks: z.array(z.string().min(1).max(240)).max(3),
  breakdown: z.object({
    skills: scoreSchema,
    experience: scoreSchema,
    rate: scoreSchema,
    english: scoreSchema,
    requirements: scoreSchema,
  }),
})
```

Implement `resolveLocale(systemLocale)` with the exact Russian-prefix rule and expose English/Russian dictionaries through `getMessages(locale)`.

- [ ] **Step 4: Run focused tests and full typecheck**

Run: `pnpm vitest run lib/analysis/schema.test.ts lib/i18n/locale.test.ts`

Expected: PASS.

Run: `pnpm typecheck`

Expected: existing mock data errors identify every fixture that needs the new required `Job.url` and history timestamp fields; update only those fixtures, then rerun to PASS.

---

### Task 3: Upwork DOM Parser and Content Script

**Files:**
- Create: `lib/upwork/parser.ts`
- Create: `lib/upwork/messages.ts`
- Create: `lib/upwork/__fixtures__/complete.html`
- Create: `lib/upwork/__fixtures__/partial.html`
- Create: `lib/upwork/parser.test.ts`
- Create: `entrypoints/upwork.content.ts`

**Interfaces:**
- Consumes: browser DOM and `Job`.
- Produces: `parseUpworkJob(document, url): ParseJobResult`; messages `{ type: "GET_CURRENT_JOB" }` and `{ type: "SCROLL_TO_APPLY" }`.

- [ ] **Step 1: Add sanitized HTML fixtures and failing parser tests**

Tests assert real parsed values rather than selector calls:

```ts
it("extracts a complete Upwork job", () => {
  document.documentElement.innerHTML = completeFixture
  const result = parseUpworkJob(document, "https://www.upwork.com/jobs/~0123456789")
  expect(result).toEqual({
    ok: true,
    job: expect.objectContaining({
      title: "Senior Python Backend Developer",
      hourlyRateMin: 30,
      hourlyRateMax: 50,
      clientRating: 4.9,
      skills: ["Python", "Django", "PostgreSQL"],
    }),
  })
})

it("returns incomplete when description is absent", () => {
  document.documentElement.innerHTML = partialFixture
  expect(parseUpworkJob(document, "https://www.upwork.com/jobs/~0123456789"))
    .toMatchObject({ ok: false, reason: "incomplete" })
})

it("returns unsupported outside an Upwork job URL", () => {
  expect(parseUpworkJob(document, "https://example.com"))
    .toEqual({ ok: false, reason: "unsupported" })
})
```

- [ ] **Step 2: Run parser tests and verify RED**

Run: `pnpm vitest run lib/upwork/parser.test.ts`

Expected: FAIL because `parseUpworkJob` does not exist.

- [ ] **Step 3: Implement parser strategies**

Use ordered helpers for JSON-LD, semantic selectors, and optional text parsing. Create stable job IDs from the URL path without hashing personal data. Return optional fields as `undefined`; require non-empty title and description.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run: `pnpm vitest run lib/upwork/parser.test.ts`

Expected: PASS with complete, partial, unsupported, and fallback cases.

- [ ] **Step 5: Add the content-script adapter**

Register only these Upwork job patterns:

```ts
export default defineContentScript({
  matches: ["https://www.upwork.com/jobs/*", "https://www.upwork.com/ab/proposals/job/*"],
  runAt: "document_idle",
  main() {
    browser.runtime.onMessage.addListener((message) => {
      if (message.type === "GET_CURRENT_JOB") {
        return Promise.resolve(parseUpworkJob(document, location.href))
      }
      if (message.type === "SCROLL_TO_APPLY") {
        return Promise.resolve(scrollToApplyAction(document))
      }
    })
  },
})
```

- [ ] **Step 6: Verify type safety**

Run: `pnpm typecheck`

Expected: PASS.

---

### Task 4: Versioned Local Storage and Calibration Memory

**Files:**
- Create: `lib/extension/storage.ts`
- Create: `lib/extension/storage.test.ts`

**Interfaces:**
- Consumes: a minimal async key/value `StorageArea` compatible with `browser.storage.local`.
- Produces: `createExtensionStore(area)`, with `load()`, `saveProfile()`, `resetProfile()`, `addAnalysis()`, `saveFeedback()`, `clearHistory()`, and `getCalibrationMemory()`.

- [ ] **Step 1: Write failing storage behavior tests**

```ts
it("keeps the newest fifty history entries", async () => {
  const store = createExtensionStore(memoryArea())
  for (let index = 0; index < 52; index += 1) {
    await store.addAnalysis(makeEntry(index))
  }
  const state = await store.load()
  expect(state.history).toHaveLength(50)
  expect(state.history[0].id).toBe("51")
})

it("returns only ten newest calibration entries", async () => {
  const store = createExtensionStore(memoryArea())
  await seedEntries(store, 12)
  expect(await store.getCalibrationMemory()).toHaveLength(10)
})

it("preserves history when resetting a profile", async () => {
  const store = createExtensionStore(memoryArea())
  await store.addAnalysis(makeEntry(1))
  await store.resetProfile()
  expect((await store.load()).history).toHaveLength(1)
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pnpm vitest run lib/extension/storage.test.ts`

Expected: FAIL because the store does not exist.

- [ ] **Step 3: Implement versioned storage**

Persist `{ version: 1, profile, history }` under one namespaced key. Serialize only JSON-safe values, clamp history to 50 on every write, return 10 compact newest memory records, and migrate missing version-1 fields to safe defaults.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pnpm vitest run lib/extension/storage.test.ts`

Expected: PASS.

---

### Task 5: Prompt Builder and OpenRouter Analysis Service

**Files:**
- Create: `lib/analysis/prompt.ts`
- Create: `lib/analysis/openrouter.ts`
- Create: `lib/analysis/service.ts`
- Create: `lib/analysis/prompt.test.ts`
- Create: `lib/analysis/service.test.ts`

**Interfaces:**
- Consumes: validated `AnalysisRequest` and an injectable `AnalysisTransport`.
- Produces: `buildAnalysisPrompt(request)`, `createOpenRouterTransport(options)`, and `analyzeJob(request, transport): Promise<FitAnalysis>`.

- [ ] **Step 1: Write failing prompt and service tests**

```ts
it("marks absent job fields instead of inventing values", () => {
  const prompt = buildAnalysisPrompt(requestWithoutBudget)
  expect(prompt.context).toContain("hourlyRate: not provided")
})

it("requests Russian user-visible fields for ru locale", () => {
  expect(buildAnalysisPrompt({ ...validRequest, locale: "ru" }).instructions)
    .toContain("Write all user-visible fields in Russian")
})

it("normalizes a contradictory model verdict", async () => {
  const transport = async () => ({ ...validAnalysis, score: 42, status: "GO" as const })
  expect((await analyzeJob(validRequest, transport)).status).toBe("NO_GO")
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pnpm vitest run lib/analysis/prompt.test.ts lib/analysis/service.test.ts`

Expected: FAIL because prompt and service modules do not exist.

- [ ] **Step 3: Implement prompt and transport boundary**

Build four explicit prompt sections from validated, length-limited data. The OpenRouter transport must use:

```ts
await client.chat.completions.create({
  model,
  messages: [
    { role: "system", content: prompt.instructions },
    { role: "user", content: prompt.input },
  ],
  response_format: {
    type: "json_schema",
    json_schema: {
      name: "fit_analysis",
      strict: true,
      schema: fitAnalysisJsonSchema,
    },
  },
})
```

Parse `response.choices[0].message.content`, validate it with `fitAnalysisSchema`, and map provider failures to `AnalysisServiceError` codes: `rate_limit`, `timeout`, `invalid_output`, and `upstream`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pnpm vitest run lib/analysis/prompt.test.ts lib/analysis/service.test.ts`

Expected: PASS without making a network request.

---

### Task 6: Secure Next.js Analyze Route

**Files:**
- Create: `app/api/analyze/route.ts`
- Create: `app/api/analyze/route.test.ts`

**Interfaces:**
- Consumes: `analysisRequestSchema`, `analyzeJob()`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and `ALLOWED_ORIGINS`.
- Produces: `POST /api/analyze` and `OPTIONS /api/analyze` JSON responses with stable error codes.

- [ ] **Step 1: Write failing route tests**

```ts
it("rejects an origin outside ALLOWED_ORIGINS", async () => {
  const response = await POST(makeRequest(validBody, "https://evil.example"))
  expect(response.status).toBe(403)
  await expect(response.json()).resolves.toEqual({ error: "origin_not_allowed" })
})

it("returns 400 for an invalid profile", async () => {
  const response = await POST(makeRequest({ ...validBody, profile: {} }, allowedOrigin))
  expect(response.status).toBe(400)
})

it("returns a validated analysis", async () => {
  setAnalysisTransportForTest(async () => validAnalysis)
  const response = await POST(makeRequest(validBody, allowedOrigin))
  expect(response.status).toBe(200)
  await expect(response.json()).resolves.toMatchObject({ score: 82, status: "GO" })
})
```

- [ ] **Step 2: Run route tests and verify RED**

Run: `pnpm vitest run app/api/analyze/route.test.ts`

Expected: FAIL because the route does not exist.

- [ ] **Step 3: Implement CORS, validation, and error mapping**

Reject bodies above the configured request limit before JSON parsing. Return stable statuses: 400 invalid request, 403 origin denied, 429 provider rate limit, 502 invalid/upstream response, and 504 timeout. Add CORS headers only for a matched origin. Do not log request bodies or raw provider responses.

- [ ] **Step 4: Run route tests and verify GREEN**

Run: `pnpm vitest run app/api/analyze/route.test.ts`

Expected: PASS.

---

### Task 7: Shared Runtime Adapters and Popup State Machine

**Files:**
- Create: `lib/extension/runtime.ts`
- Create: `lib/extension/browser-adapter.ts`
- Create: `lib/extension/preview-adapter.ts`
- Create: `components/extension/extension-app.tsx`
- Create: `components/extension/extension-app.test.tsx`
- Modify: `app/page.tsx`
- Modify: `components/extension/loading-state.tsx`
- Remove: page-owned state and mock analysis dispatch from `app/page.tsx`

**Interfaces:**
- Consumes: parser messaging, extension store, backend route, locale dictionaries.
- Produces: `ExtensionRuntime` and `<ExtensionApp runtime={runtime} previewControls={boolean} />`.

- [ ] **Step 1: Write failing state-flow tests**

Cover first-run onboarding, unsupported page, successful analysis persistence, failed analysis not persisted, and locale selection:

```tsx
it("stores and displays a successful analysis", async () => {
  const runtime = createTestRuntime({ profile: defaultProfile, job: detectedJob, analysis: goAnalysis })
  render(<ExtensionApp runtime={runtime} />)
  await user.click(await screen.findByRole("button", { name: /analyze job/i }))
  expect(await screen.findByText("82")).toBeInTheDocument()
  expect(runtime.savedEntries).toHaveLength(1)
})

it("does not store a failed analysis", async () => {
  const runtime = createTestRuntime({ analyzeError: "network" })
  render(<ExtensionApp runtime={runtime} />)
  await user.click(await screen.findByRole("button", { name: /analyze job/i }))
  expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument()
  expect(runtime.savedEntries).toHaveLength(0)
})
```

- [ ] **Step 2: Run component tests and verify RED**

Run: `pnpm vitest run components/extension/extension-app.test.tsx`

Expected: FAIL because the shared state machine does not exist.

- [ ] **Step 3: Implement runtime boundaries and state machine**

The runtime exposes methods for locale, state loading, current-job retrieval, analysis, persistence, source-tab action, and popup closing. Remove timer-owned business completion from `LoadingState`; the actual analysis promise controls completion. Keep preview scenario controls behind `previewControls`.

- [ ] **Step 4: Replace `app/page.tsx` with the preview adapter**

Render the same shared app used by the popup:

```tsx
"use client"

import { ExtensionApp } from "@/components/extension/extension-app"
import { createPreviewRuntime } from "@/lib/extension/preview-adapter"

const runtime = createPreviewRuntime()

export default function Page() {
  return <ExtensionApp runtime={runtime} previewControls />
}
```

- [ ] **Step 5: Run component tests and typecheck**

Run: `pnpm vitest run components/extension/extension-app.test.tsx`

Expected: PASS.

Run: `pnpm typecheck`

Expected: PASS.

---

### Task 8: Localized UI, Feedback, History, and Profile Actions

**Files:**
- Create: `components/extension/feedback-screen.tsx`
- Create: `components/extension/feedback-screen.test.tsx`
- Modify: `components/extension/app-header.tsx`
- Modify: `components/extension/bottom-navigation.tsx`
- Modify: `components/extension/details-screen.tsx`
- Modify: `components/extension/empty-state.tsx`
- Modify: `components/extension/error-state.tsx`
- Modify: `components/extension/history-screen.tsx`
- Modify: `components/extension/job-summary.tsx`
- Modify: `components/extension/onboarding.tsx`
- Modify: `components/extension/profile-form.tsx`
- Modify: `components/extension/profile-screen.tsx`
- Modify: `components/extension/ready-screen.tsx`
- Modify: `components/extension/result-screen.tsx`

**Interfaces:**
- Consumes: typed localized messages and `AnalysisFeedback`.
- Produces: fully localized English/Russian UI, score correction, optional note, clear-history confirmation, and reset-profile confirmation.

- [ ] **Step 1: Write failing feedback and localization tests**

```tsx
it("saves a corrected score and optional note", async () => {
  const onSave = vi.fn()
  render(<FeedbackScreen analysis={goAnalysis} messages={messages.en} onSave={onSave} onCancel={() => {}} />)
  await user.clear(screen.getByLabelText(/correct score/i))
  await user.type(screen.getByLabelText(/correct score/i), "65")
  await user.type(screen.getByLabelText(/note/i), "Timezone overlap is a blocker")
  await user.click(screen.getByRole("button", { name: /save feedback/i }))
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ correctedScore: 65 }))
})
```

Add a Russian render assertion for the header, Analyze button, result verdict copy, and Retry button.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `pnpm vitest run components/extension/feedback-screen.test.tsx components/extension/extension-app.test.tsx`

Expected: FAIL because feedback and localized props are absent.

- [ ] **Step 3: Implement feedback and localized copy**

Replace hard-coded user-visible strings with typed dictionary values. Validate corrected score from 0 to 100 and note length at 500 characters. Require browser-native confirmation before destructive history/profile actions.

- [ ] **Step 4: Run UI tests and verify GREEN**

Run: `pnpm vitest run components/extension/feedback-screen.test.tsx components/extension/extension-app.test.tsx`

Expected: PASS.

---

### Task 9: Production Popup and Packaging

**Files:**
- Create: `entrypoints/popup/index.html`
- Create: `entrypoints/popup/main.tsx`
- Create: `entrypoints/popup/style.css`
- Create: `entrypoints/popup/App.tsx`
- Create: `entrypoints/popup/App.test.tsx`
- Modify: `app/globals.css`
- Modify: `.gitignore` if present; otherwise create `.gitignore`

**Interfaces:**
- Consumes: `ExtensionApp`, browser runtime adapter, shared Tailwind styles.
- Produces: WXT popup bundle in `.output/chrome-mv3` and extension zip.

- [ ] **Step 1: Add a build-level popup smoke test**

Add a test that renders `<App />` with an injected browser runtime factory and asserts the branded header appears. Keep Chrome APIs behind the adapter so the component is testable without a real browser.

- [ ] **Step 2: Run the smoke test and verify RED**

Run: `pnpm vitest run entrypoints/popup/App.test.tsx`

Expected: FAIL because the popup entrypoint does not exist.

- [ ] **Step 3: Mount the popup and share styles**

Set a popup body size of 400px by 600px with a safe maximum height, import Tailwind/shared theme CSS, mount React with `createRoot`, and exclude preview controls. Add `.output`, `.wxt`, and extension zip artifacts to `.gitignore`.

- [ ] **Step 4: Run the popup test and production extension build**

Run: `pnpm vitest run entrypoints/popup/App.test.tsx`

Expected: PASS.

Run: `pnpm build:extension`

Expected: exit 0 and `.output/chrome-mv3/manifest.json` contains Manifest V3, popup, storage/activeTab permissions, localized metadata, and only Upwork/backend host access.

---

### Task 10: Documentation and Full Verification

**Files:**
- Create: `README.md` if absent; otherwise modify it.
- Modify: `.env.example`
- Modify: any source or test files required by verification failures, without expanding feature scope.

**Interfaces:**
- Consumes: complete application.
- Produces: reproducible local backend setup, extension development/build/install instructions, and a verified release artifact.

- [ ] **Step 1: Document exact setup and loading steps**

README must cover:

1. `pnpm install`;
2. copying `.env.example` to `.env.local` and setting `OPENROUTER_API_KEY`;
3. running `pnpm dev` for the backend/preview;
4. setting `WXT_PUBLIC_API_BASE_URL` and running `pnpm dev:extension`;
5. loading `.output/chrome-mv3` with Chrome “Load unpacked”;
6. production build and zip commands;
7. Russian/English locale behavior;
8. local-only storage and current MVP security limitations.

- [ ] **Step 2: Run the complete automated verification suite**

Run: `pnpm test`

Expected: all tests PASS with no unhandled errors or warnings.

Run: `pnpm typecheck`

Expected: exit 0.

Run: `pnpm lint`

Expected: exit 0 with no warnings.

Run: `pnpm build:web`

Expected: Next.js production build exits 0 and `/api/analyze` is emitted as a dynamic route.

Run: `pnpm build:extension`

Expected: WXT production build exits 0.

- [ ] **Step 3: Inspect the built manifest and artifact**

Run: `sed -n '1,240p' .output/chrome-mv3/manifest.json`

Expected: `manifest_version` is 3; permissions are minimal; popup and content script paths exist; Upwork patterns and configured backend origin are the only host access.

Run: `find .output/chrome-mv3 -maxdepth 3 -type f | sort`

Expected: popup HTML/JS/CSS, content script, icons, locale files, and manifest are present with no `.env` file or API key.

- [ ] **Step 4: Perform manual browser verification when Chrome is available**

Load `.output/chrome-mv3` unpacked. Verify onboarding, an unsupported page, a supported Upwork job, successful analysis with a configured key, feedback persistence, history reopening, profile editing, Russian browser locale, and English fallback. Record any browser-only defect as a failing automated regression test before fixing it.
