# Profile Preferences and Skill Suggestions Implementation Plan

> **Scope update — 2026-10-12:** The user chose FitCheck as a website-only product and authorized removal of the extension code, builds, and authentication. This document is a historical implementation record; completed steps, test results, and migration history remain evidence of the work at that time. Extension steps and compatibility requirements are superseded and must not be executed or restored. Future work uses website cookie sessions with web-origin CSRF, website IndexedDB as the legacy import source, independent same-account sessions across devices, and website/backend CI. See the current backend foundation, storage, and authentication specifications.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add on-demand DeepSeek skill suggestions and richer income/work-format preferences to the FitCheck website profile, persist them locally, and use them in vacancy analysis.

**Architecture:** Extend the shared validated profile shape and normalize legacy IndexedDB records at the repository boundary. Add a focused DeepSeek suggestion transport and server route, expose it through the existing website API abstraction, then make `ProfileEditor` consume that abstraction without receiving provider credentials.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Zod 4, OpenAI Node SDK against DeepSeek, IndexedDB, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-25-profile-preferences-and-skill-suggestions-design.md`

## Global Constraints

- Website UI only; extension UI gets compatibility data changes but no new visible controls.
- Skill suggestions run only after the user presses the button.
- DeepSeek thinking mode is explicitly disabled and no provider key reaches the browser.
- Suggestion responses contain at most 10 unique skills.
- Russian uses rubles; English uses US dollars; locale switching does not convert values.
- At least one work format is required.
- Existing IndexedDB profiles load without account recreation or data deletion.
- No remote database or mock suggestion fallback is added.

---

### Task 1: Extend and migrate the profile model

**Files:**
- Modify: `lib/types.ts`
- Modify: `lib/analysis/schema.ts`
- Modify: `lib/analysis/schema.test.ts`
- Modify: `lib/web/repository.ts`
- Modify: `lib/web/repository.test.ts`
- Modify: `lib/mock-data.ts`

**Interfaces:**
- Produces: `WorkFormat = "remote" | "office" | "hybrid"`.
- Produces: required `FreelancerProfile.desiredMonthlyIncome: number` and `FreelancerProfile.workFormats: WorkFormat[]`.
- Produces: `normalizeStoredProfile(value: unknown): FreelancerProfile`, used when loading IndexedDB records.

- [ ] **Step 1: Write failing schema and repository migration tests**

Add literal cases proving a rate of `2500` is accepted, negative/non-finite money is rejected, work formats require one unique enum value, and a stored legacy profile loads as:

```ts
{
  ...legacyProfile,
  desiredMonthlyIncome: 0,
  workFormats: ["remote"],
}
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `npm test -- lib/analysis/schema.test.ts lib/web/repository.test.ts`

Expected: failures because the new fields/default migration do not exist and the old 1,000 maximum rejects the large rate.

- [ ] **Step 3: Implement the minimum validated model and read migration**

Use a finite monetary schema capped at `100_000_000`, require `.min(1)` work formats, and use a `Set` refinement for uniqueness. Normalize only missing new properties before parsing:

```ts
const candidate = value as Partial<FreelancerProfile>
return freelancerProfileSchema.parse({
  ...candidate,
  desiredMonthlyIncome: candidate.desiredMonthlyIncome ?? 0,
  workFormats: candidate.workFormats ?? ["remote"],
})
```

Call the normalizer at the `loadSnapshot()` repository boundary. Update the default profile and typed fixtures with explicit values.

- [ ] **Step 4: Run focused tests and typecheck**

Run: `npm test -- lib/analysis/schema.test.ts lib/web/repository.test.ts && npm run typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/types.ts lib/analysis/schema.ts lib/analysis/schema.test.ts lib/web/repository.ts lib/web/repository.test.ts lib/mock-data.ts
git commit -m "feat: extend freelancer profile preferences"
```

### Task 2: Add profile preferences to analysis prompts

**Files:**
- Modify: `lib/analysis/prompt.ts`
- Modify: `lib/analysis/prompt.test.ts`

**Interfaces:**
- Consumes: extended `FreelancerProfile` from Task 1.
- Produces: locale-derived currency formatting within `buildAnalysisPrompt(request)`.

- [ ] **Step 1: Write failing prompt tests**

Add hand-authored expectations for English and Russian requests:

```ts
expect(en.input).toContain("Preferred hourly rate: $2500")
expect(en.input).toContain("Desired monthly income: $12000")
expect(en.input).toContain("Acceptable work formats: remote, hybrid")
expect(ru.input).toContain("Preferred hourly rate: ₽2500")
expect(ru.input).toContain("Desired monthly income: ₽300000")
```

Also assert that instructions say missing vacancy income or work-mode evidence must not be treated as a mismatch.

- [ ] **Step 2: Run the prompt tests and verify RED**

Run: `npm test -- lib/analysis/prompt.test.ts`

Expected: FAIL because only the dollar hourly rate is currently emitted.

- [ ] **Step 3: Implement locale-aware prompt fields**

Derive `currency = locale === "ru" ? "₽" : "$"`, add the new profile lines, and extend the evaluation instruction without changing the JSON response schema.

- [ ] **Step 4: Run prompt and analysis tests**

Run: `npm test -- lib/analysis/prompt.test.ts lib/analysis/service.test.ts app/api/analyze/route.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/analysis/prompt.ts lib/analysis/prompt.test.ts
git commit -m "feat: analyze income and work format preferences"
```

### Task 3: Build the DeepSeek skill-suggestion service

**Files:**
- Create: `lib/skill-suggestions/schema.ts`
- Create: `lib/skill-suggestions/service.ts`
- Create: `lib/skill-suggestions/service.test.ts`
- Create: `lib/skill-suggestions/deepseek.ts`
- Create: `lib/skill-suggestions/deepseek.test.ts`

**Interfaces:**
- Produces: `skillSuggestionRequestSchema` for `{ specialization: string; locale: Locale }`.
- Produces: `skillSuggestionResponseSchema` for `{ skills: string[] }` with zero to ten items.
- Produces: `SkillSuggestionServiceError` using `rate_limit | timeout | invalid_output | upstream`.
- Produces: `suggestSkills(request, transport): Promise<{ skills: string[] }>`.
- Produces: `createDeepSeekSkillSuggestionTransport({ apiKey, model })`.

- [ ] **Step 1: Write failing normalization and transport tests**

Prove service output trims values, removes case-insensitive duplicates, and limits the result to 10. At the real HTTP serialization boundary, assert:

```ts
expect(requestedBody).toMatchObject({
  model: "deepseek-v4-flash",
  max_tokens: 500,
  response_format: { type: "json_object" },
  thinking: { type: "disabled" },
})
```

Use a complete Chat Completions fixture whose content is `{"skills":["Python","FastAPI"]}`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `npm test -- lib/skill-suggestions/service.test.ts lib/skill-suggestions/deepseek.test.ts`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement schemas, normalization, provider call, and error mapping**

Keep provider-specific `thinking` typing isolated as in `lib/analysis/deepseek.ts`. Prompt for concise skill names, localize generic competencies using the requested locale, preserve conventional technology spelling, parse JSON, and map SDK failures to stable service errors.

- [ ] **Step 4: Run focused tests and typecheck**

Run: `npm test -- lib/skill-suggestions/service.test.ts lib/skill-suggestions/deepseek.test.ts && npm run typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/skill-suggestions
git commit -m "feat: add DeepSeek skill suggestion service"
```

### Task 4: Expose the suggestion service through a protected route

**Files:**
- Create: `app/api/skill-suggestions/handler.ts`
- Create: `app/api/skill-suggestions/handler.test.ts`
- Create: `app/api/skill-suggestions/route.ts`
- Create: `app/api/skill-suggestions/route.test.ts`

**Interfaces:**
- Consumes: schemas, service errors, and DeepSeek transport from Task 3.
- Produces: `POST /api/skill-suggestions` and matching `OPTIONS` behavior.

- [ ] **Step 1: Write failing handler and route tests**

Cover same-origin acceptance, foreign-origin rejection, malformed/oversized input, valid skills, 429/504/502 mappings, missing `DEEPSEEK_API_KEY`, and environment-selected `DEEPSEEK_MODEL`.

- [ ] **Step 2: Run route tests and verify RED**

Run: `npm test -- app/api/skill-suggestions/handler.test.ts app/api/skill-suggestions/route.test.ts`

Expected: FAIL because the route does not exist.

- [ ] **Step 3: Implement handler and route**

Use a 5,000-character body limit, the analysis route's allowlist behavior, and stable public codes prefixed with `suggestions_` for provider failures. Construct the real DeepSeek transport only when the server key exists.

- [ ] **Step 4: Run route tests**

Run: `npm test -- app/api/skill-suggestions/handler.test.ts app/api/skill-suggestions/route.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/skill-suggestions
git commit -m "feat: expose skill suggestions API"
```

### Task 5: Add the website API contract

**Files:**
- Modify: `lib/web/api.ts`
- Modify: `lib/web/api.test.ts`

**Interfaces:**
- Produces: `WebsiteApi.suggestSkills(request): Promise<string[]>`.
- Extends: `WebApiErrorCode` with stable suggestion error codes.

- [ ] **Step 1: Write failing client tests**

Assert that the client posts specialization and locale, returns a validated skills array, maps a `suggestions_timeout` response, and rejects malformed success data containing more than 10 skills or empty strings.

- [ ] **Step 2: Run the API client tests and verify RED**

Run: `npm test -- lib/web/api.test.ts`

Expected: FAIL because `suggestSkills` is absent.

- [ ] **Step 3: Implement the API method**

Reuse the existing `post()` and `errorFrom()` helpers, validate with `skillSuggestionResponseSchema`, and expose the method on `websiteApi`.

- [ ] **Step 4: Run API tests and typecheck**

Run: `npm test -- lib/web/api.test.ts && npm run typecheck`

Expected: PASS after updating dependency injection sites and test doubles to implement the new interface.

- [ ] **Step 5: Commit**

```bash
git add lib/web/api.ts lib/web/api.test.ts components/web/website-app.test.tsx
git commit -m "feat: add website skill suggestion client"
```

### Task 6: Implement the profile-editor experience

**Files:**
- Modify: `components/web/profile-editor.tsx`
- Modify: `components/web/profile-editor.test.tsx`
- Modify: `components/web/website-app.tsx`
- Modify: `components/web/website-app.test.tsx`
- Modify: `lib/i18n/web-messages.ts`

**Interfaces:**
- `ProfileEditor` consumes `locale: Locale` and `onSuggestSkills(input): Promise<string[]>` in addition to the existing profile/save properties.
- `WebsiteApp` passes `api.suggestSkills` and maps stable errors to localized profile messages.

- [ ] **Step 1: Write failing editor interaction tests**

Cover these observable behaviors:

```ts
expect(screen.getByRole("button", { name: "Suggest skills" })).toBeDisabled()
await user.type(screen.getByLabelText("Specialization"), "Backend Developer")
await user.click(screen.getByRole("button", { name: "Suggest skills" }))
expect(await screen.findByRole("button", { name: "Python" })).toBeVisible()
await user.click(screen.getByRole("button", { name: "Python" }))
expect(screen.getByLabelText("Skills")).toHaveValue("TypeScript, Python")
```

Also prove case-insensitive duplicate exclusion, stale-suggestion clearing, inline error rendering, `2500` hourly rate acceptance, locale currency labels, monthly income serialization, and disabled save with no checked work format.

- [ ] **Step 2: Run component tests and verify RED**

Run: `npm test -- components/web/profile-editor.test.tsx components/web/website-app.test.tsx`

Expected: FAIL because the controls, callbacks, and copy do not exist.

- [ ] **Step 3: Implement focused state and controls**

Keep suggestion loading/error state inside `ProfileEditor`; clear it when specialization changes. Filter suggestions against parsed comma-separated skills with `toLocaleLowerCase()`. Render suggestion chips as `type="button"`. Add monthly-income input, currency suffix copy, and controlled work-format checkboxes. Validate the complete object with `freelancerProfileSchema` before save.

- [ ] **Step 4: Wire API and localized errors in WebsiteApp**

Pass `locale`, call `api.suggestSkills({ specialization, locale })`, and map `suggestions_rate_limit`, `suggestions_timeout`, `suggestions_invalid_output`, `suggestions_upstream`, `server_not_configured`, `network_error`, and `invalid_response` to new English/Russian messages.

- [ ] **Step 5: Run component and website tests**

Run: `npm test -- components/web/profile-editor.test.tsx components/web/website-app.test.tsx lib/web/api.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add components/web/profile-editor.tsx components/web/profile-editor.test.tsx components/web/website-app.tsx components/web/website-app.test.tsx lib/i18n/web-messages.ts
git commit -m "feat: add richer website profile editor"
```

### Task 7: Preserve extension build compatibility

**Files:**
- Modify: `components/extension/profile-form.tsx`
- Modify: `components/extension/profile-form.test.tsx`
- Modify: `components/extension/onboarding.tsx`
- Modify: `lib/extension/storage.ts`
- Modify: `lib/extension/storage.test.ts`

**Interfaces:**
- Consumes: the required profile fields from Task 1.
- Preserves: current extension UI and runtime API.

- [ ] **Step 1: Write or adjust a failing legacy extension storage test**

Prove that a stored legacy extension profile receives `desiredMonthlyIncome: 0` and `workFormats: ["remote"]`, while visible extension behavior is unchanged.

- [ ] **Step 2: Run extension tests and verify RED**

Run: `npm test -- lib/extension/storage.test.ts components/extension/profile-form.test.tsx components/extension/extension-app.test.tsx`

Expected: FAIL on missing compatibility fields or legacy normalization.

- [ ] **Step 3: Add compatibility defaults without new extension controls**

When the extension form saves, preserve initial new values or use the same defaults. Normalize legacy stored profiles at load. Do not add the website's income or work-format controls to the extension.

- [ ] **Step 4: Run extension tests and typecheck**

Run: `npm test -- lib/extension/storage.test.ts components/extension/profile-form.test.tsx components/extension/extension-app.test.tsx && npm run typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add components/extension/profile-form.tsx components/extension/profile-form.test.tsx components/extension/onboarding.tsx lib/extension/storage.ts lib/extension/storage.test.ts
git commit -m "chore: preserve extension profile compatibility"
```

### Task 8: Verify, review, deploy, and exercise the real feature

**Files:**
- No planned source changes; fix only review or verification findings tied to this feature.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified `dev` deployment.

- [ ] **Step 1: Run full automated verification**

Run:

```bash
npm test
npm run typecheck
npm run lint
npx next build --webpack
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 2: Request code review**

Use `superpowers:requesting-code-review` against the feature commit range. Resolve every Critical and Important finding, then rerun Step 1.

- [ ] **Step 3: Push the dev branch and deploy Dokploy**

Push only the committed feature work to `origin/dev`, trigger application `4cwEJ5gtixQ_Dcxm8lGnM`, and wait for deployment status `done`. Do not print secrets.

- [ ] **Step 4: Verify the public API**

POST one Russian specialization and one English specialization to `https://dev-fitcheck.dokploy.gcexp.ru/api/skill-suggestions`. Require HTTP 200, one to ten unique non-empty skills, and no provider fields in the response.

- [ ] **Step 5: Verify the public website flow**

Use the website profile page to request suggestions, add one by clicking, enter a rate above 1,000, enter monthly income, select at least one work format, save, reload, and confirm the values persist. Then analyze a vacancy and require HTTP 200.

- [ ] **Step 6: Report evidence**

Report the deployed commit, public URL, command counts/results, and live checks without exposing API keys or local profile secrets.
