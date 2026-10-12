# FitCheck Website Implementation Plan

> **Scope update — 2026-10-12:** The user chose FitCheck as a website-only product and authorized removal of the extension code, builds, and authentication. This document is a historical implementation record; completed steps, test results, and migration history remain evidence of the work at that time. Extension steps and compatibility requirements are superseded and must not be executed or restored. Future work uses website cookie sessions with web-origin CSRF, website IndexedDB as the legacy import source, independent same-account sessions across devices, and website/backend CI. See the current backend foundation, storage, and authentication specifications.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the popup-style mock preview with a responsive website where a locally remembered user can submit a real vacancy by text or public URL and receive a persisted, real OpenRouter fit analysis in Russian or English.

**Architecture:** The Next.js App Router website uses a focused client application and a versioned native IndexedDB repository for all user-owned data. Stateless Node.js route handlers perform SSRF-safe public-page extraction and server-only OpenRouter analysis; React components consume those boundaries through typed interfaces so tests can substitute in-memory implementations.

**Tech Stack:** Next.js 16.3 App Router, React 19, TypeScript, Tailwind CSS 4, Base UI/shadcn components, Zod 4, native IndexedDB and Web Crypto, Cheerio, Node HTTP/HTTPS/DNS APIs, Vitest, React Testing Library, fake-indexeddb.

**Spec:** `docs/superpowers/specs/2026-08-25-fitcheck-website-design.md`

## Global Constraints

- The website is the only supported product surface for this iteration; do not redesign or extend the Chrome extension.
- Production website code must not import `lib/mock-data.ts` or `lib/extension/preview-adapter.ts`.
- Profile, locale, vacancy draft, history, feedback, local credentials, and active session persist in IndexedDB and are isolated by `userId`.
- Local login is explicitly described as browser-only; there is no server user database, verification, recovery, OAuth, or cross-device sync.
- Vacancy input supports pasted text and any public HTTP or HTTPS URL, with manual fallback when extraction is unavailable.
- Arbitrary URL fetching must reject private/reserved targets and revalidate every redirect.
- OpenRouter credentials remain server-only, and production never substitutes mock analysis data.
- RU/EN switching is manual, immediate, persistent, and controls both UI and LLM output.
- All recoverable errors preserve current user input.
- Read `node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md`, `node_modules/next/dist/docs/01-app/01-getting-started/15-route-handlers.md`, and `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/route.md` before modifying App Router code.
- Each task follows red-green-refactor and ends in a focused commit.

## Target File Structure

- `lib/web/types.ts` — website-only domain records, workflow states, and repository interface.
- `lib/web/schemas.ts` — Zod validation and normalization for local accounts and vacancy drafts.
- `lib/web/password.ts` — salted PBKDF2 derivation and constant-time comparison over Web Crypto.
- `lib/web/repository.ts` — native IndexedDB implementation of the website repository.
- `lib/web/memory-repository.ts` — deterministic in-memory repository for component tests.
- `lib/web/api.ts` — typed browser client for extraction and analysis endpoints.
- `lib/web/history.ts` — history-entry construction and calibration-memory projection.
- `lib/extraction/network.ts` — URL validation, address classification, pinned DNS lookup, redirect policy, timeout, and byte limits.
- `lib/extraction/content.ts` — HTML/text to editable vacancy draft normalization.
- `lib/extraction/schema.ts` — extraction request and response contracts.
- `app/api/extract/handler.ts` and `app/api/extract/route.ts` — testable extraction handler and Node route.
- `components/web/website-app.tsx` — top-level authentication and product state orchestration.
- `components/web/auth-screen.tsx` — create-account and sign-in modes.
- `components/web/app-shell.tsx` — responsive navigation, language switch, account menu.
- `components/web/profile-editor.tsx` — real profile creation and editing.
- `components/web/vacancy-source.tsx` — URL and pasted-text input.
- `components/web/vacancy-review.tsx` — normalized editable vacancy before analysis.
- `components/web/analysis-result.tsx` — score, decision, explanation, strengths, risks, details, and feedback entry.
- `components/web/history-view.tsx` — persisted analysis list and reopening behavior.
- `lib/i18n/web-messages.ts` — typed RU/EN website copy.
- `app/page.tsx`, `app/layout.tsx`, and `app/globals.css` — production website entry, metadata, and responsive visual system.

---

### Task 1: Website Domain Contracts, Validation, and Password Derivation

**Files:**
- Create: `lib/web/types.ts`
- Create: `lib/web/schemas.ts`
- Create: `lib/web/password.ts`
- Test: `lib/web/schemas.test.ts`
- Test: `lib/web/password.test.ts`
- Modify: `lib/types.ts`
- Modify: `lib/analysis/schema.ts`
- Modify: `lib/analysis/schema.test.ts`

**Interfaces:**
- Consumes: existing `FreelancerProfile`, `Job`, `FitAnalysis`, `AnalysisFeedback`, and `Locale` from `lib/types.ts`.
- Produces: `LocalUser`, `LocalSession`, `UserPreferences`, `VacancySourceMode`, `VacancyDraft`, `WebHistoryEntry`, `WebsiteSnapshot`, `WebsiteRepository`, `normalizeEmail(email): string`, `vacancyDraftSchema`, `derivePassword(password, salt?): Promise<PasswordDigest>`, and `verifyPassword(password, digest): Promise<boolean>`.

- [ ] **Step 1: Write failing domain validation tests**

```ts
import { describe, expect, it } from "vitest"
import { normalizeEmail, vacancyDraftSchema } from "./schemas"

describe("website schemas", () => {
  it("normalizes local account emails", () => {
    expect(normalizeEmail("  Person@Example.COM ")).toBe("person@example.com")
  })

  it("accepts a manual vacancy without a source URL", () => {
    expect(vacancyDraftSchema.parse({
      id: "draft-1",
      sourceMode: "text",
      title: "Senior TypeScript Engineer",
      description: "Build and maintain a multi-tenant SaaS application.",
      skills: ["TypeScript"],
      updatedAt: "2026-08-25T12:00:00.000Z",
    }).sourceMode).toBe("text")
  })

  it("rejects private or non-http source values at the draft boundary", () => {
    expect(() => vacancyDraftSchema.parse({
      id: "draft-2",
      sourceMode: "url",
      sourceUrl: "file:///etc/passwd",
      title: "Role",
      description: "A sufficiently descriptive vacancy body.",
      skills: [],
      updatedAt: "2026-08-25T12:00:00.000Z",
    })).toThrow()
  })
})
```

- [ ] **Step 2: Run the schema tests and confirm RED**

Run: `pnpm vitest run lib/web/schemas.test.ts`

Expected: FAIL because `lib/web/schemas.ts` does not exist.

- [ ] **Step 3: Define focused website types and schemas**

```ts
export interface VacancyDraft {
  id: string
  sourceMode: "url" | "text"
  sourceUrl?: string
  rawSource?: string
  title: string
  description: string
  skills: string[]
  hourlyRateMin?: number
  hourlyRateMax?: number
  fixedBudget?: number
  updatedAt: string
}

export interface WebHistoryEntry {
  id: string
  userId: string
  job: Job
  profile: FreelancerProfile
  analysis: FitAnalysis
  feedback?: AnalysisFeedback
  createdAt: string
}
```

Define `WebsiteRepository` with exact async methods:

```ts
export interface WebsiteRepository {
  createUser(input: { name: string; email: string; password: string }): Promise<LocalUser>
  authenticate(email: string, password: string): Promise<LocalUser>
  loadSnapshot(): Promise<WebsiteSnapshot>
  signOut(): Promise<void>
  saveLocale(userId: string, locale: Locale): Promise<void>
  saveProfile(userId: string, profile: FreelancerProfile): Promise<void>
  saveDraft(userId: string, draft: VacancyDraft | null): Promise<void>
  addHistory(entry: WebHistoryEntry): Promise<void>
  saveFeedback(userId: string, entryId: string, feedback: AnalysisFeedback): Promise<void>
  clearHistory(userId: string): Promise<void>
  deleteUser(userId: string): Promise<void>
}
```

Make `Job.url` optional in `lib/types.ts` and change `jobSchema.url` to `z.url().max(2000).optional()` so manually pasted vacancies do not receive a fabricated URL.

- [ ] **Step 4: Write failing password tests**

```ts
import { describe, expect, it } from "vitest"
import { derivePassword, verifyPassword } from "./password"

describe("local password derivation", () => {
  it("uses a unique salt and verifies only the matching password", async () => {
    const first = await derivePassword("correct horse battery staple")
    const second = await derivePassword("correct horse battery staple")
    expect(first.salt).not.toBe(second.salt)
    await expect(verifyPassword("correct horse battery staple", first)).resolves.toBe(true)
    await expect(verifyPassword("wrong password", first)).resolves.toBe(false)
  })
})
```

- [ ] **Step 5: Implement PBKDF2 password helpers**

Use Web Crypto PBKDF2 with SHA-256, a random 16-byte salt, 210,000 iterations, and a 256-bit result. Encode salt and hash as base64. Compare decoded result bytes with an XOR accumulator rather than returning on the first mismatch.

```ts
const parameters = (salt: Uint8Array) => ({
  name: "PBKDF2",
  hash: "SHA-256",
  salt,
  iterations: 210_000,
})

export async function derivePassword(password: string, encodedSalt?: string): Promise<PasswordDigest> {
  const salt = encodedSalt ? fromBase64(encodedSalt) : crypto.getRandomValues(new Uint8Array(16))
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"])
  const hash = await crypto.subtle.deriveBits(parameters(salt), key, 256)
  return { salt: toBase64(salt), hash: toBase64(new Uint8Array(hash)) }
}
```

- [ ] **Step 6: Run focused tests and existing analysis tests**

Run: `pnpm vitest run lib/web/schemas.test.ts lib/web/password.test.ts lib/analysis/schema.test.ts lib/analysis/prompt.test.ts`

Expected: PASS, including manual jobs with no URL.

- [ ] **Step 7: Commit Task 1**

```bash
git add lib/types.ts lib/web/types.ts lib/web/schemas.ts lib/web/password.ts lib/web/schemas.test.ts lib/web/password.test.ts lib/analysis/schema.ts lib/analysis/schema.test.ts
git commit -m "feat: define website domain and local credentials"
```

---

### Task 2: Versioned IndexedDB Repository

**Files:**
- Modify: `package.json`
- Modify: `pnpm-lock.yaml`
- Create: `lib/web/repository.ts`
- Create: `lib/web/memory-repository.ts`
- Test: `lib/web/repository.test.ts`

**Interfaces:**
- Consumes: `WebsiteRepository`, record types, `normalizeEmail`, `derivePassword`, and `verifyPassword` from Task 1.
- Produces: `createWebsiteRepository(databaseName?: string): WebsiteRepository`, `createMemoryWebsiteRepository(seed?): WebsiteRepository`, `LocalAuthError` with codes `duplicate_email`, `unknown_email`, and `incorrect_password`.

- [ ] **Step 1: Add deterministic IndexedDB test support**

Run: `pnpm add -D fake-indexeddb`

Expected: `package.json` and `pnpm-lock.yaml` include `fake-indexeddb` under dev dependencies.

- [ ] **Step 2: Write failing repository lifecycle tests**

```ts
import "fake-indexeddb/auto"
import { beforeEach, describe, expect, it } from "vitest"
import { createWebsiteRepository, LocalAuthError } from "./repository"

describe("IndexedDB website repository", () => {
  let repo: ReturnType<typeof createWebsiteRepository>

  beforeEach(() => {
    repo = createWebsiteRepository(`fitcheck-test-${crypto.randomUUID()}`)
  })

  it("creates a user, restores the session, and authenticates after sign out", async () => {
    const user = await repo.createUser({ name: "Nikita", email: "ME@EXAMPLE.COM", password: "password-123" })
    expect((await repo.loadSnapshot()).user?.id).toBe(user.id)
    await repo.signOut()
    expect((await repo.loadSnapshot()).user).toBeNull()
    await expect(repo.authenticate("me@example.com", "password-123")).resolves.toMatchObject({ id: user.id })
  })

  it("isolates profile, draft, and history by active user", async () => {
    const first = await repo.createUser({ name: "First", email: "first@example.com", password: "password-123" })
    await repo.saveProfile(first.id, {
      specialization: "Backend Developer",
      skills: ["TypeScript"],
      experienceYears: 4,
      preferredRate: 40,
      englishLevel: "Upper Intermediate",
    })
    await repo.signOut()
    await repo.createUser({ name: "Second", email: "second@example.com", password: "password-456" })
    expect((await repo.loadSnapshot()).profile).toBeNull()
  })

  it("rejects duplicate emails and incorrect passwords with typed codes", async () => {
    await repo.createUser({ name: "First", email: "first@example.com", password: "password-123" })
    await expect(repo.createUser({ name: "Again", email: "FIRST@example.com", password: "password-456" }))
      .rejects.toMatchObject<Partial<LocalAuthError>>({ code: "duplicate_email" })
    await repo.signOut()
    await expect(repo.authenticate("first@example.com", "wrong"))
      .rejects.toMatchObject<Partial<LocalAuthError>>({ code: "incorrect_password" })
  })
})
```

- [ ] **Step 3: Run repository tests and confirm RED**

Run: `pnpm vitest run lib/web/repository.test.ts`

Expected: FAIL because the repository does not exist.

- [ ] **Step 4: Implement the IndexedDB schema and request helpers**

Open database version 1 with stores and keys:

```ts
const stores = {
  users: { keyPath: "id", emailIndex: { name: "email", keyPath: "email", unique: true } },
  profiles: { keyPath: "userId" },
  preferences: { keyPath: "userId" },
  drafts: { keyPath: "userId" },
  history: { keyPath: "id", userIndex: { name: "userId", keyPath: "userId" } },
  meta: { keyPath: "key" },
} as const
```

Wrap `IDBRequest` and transaction completion in promises. `loadSnapshot()` reads the `activeUserId` meta record and then loads only that user's records. `addHistory()` deletes entries after the newest 50 for the same user. `deleteUser()` deletes the user and every record returned by the `userId` indexes in one readwrite transaction.

```ts
function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
    transaction.onabort = () => reject(transaction.error)
  })
}
```

- [ ] **Step 5: Implement the in-memory repository with the same interface**

Use Maps keyed by normalized email and user id. Return `structuredClone` values from reads so React tests cannot mutate repository state by reference.

```ts
const clone = <T,>(value: T): T => structuredClone(value)
const usersById = new Map<string, LocalUser>()
const userIdByEmail = new Map<string, string>()
const profilesByUserId = new Map<string, FreelancerProfile>()
const draftsByUserId = new Map<string, VacancyDraft>()
const historyById = new Map<string, WebHistoryEntry>()
let activeUserId: string | null = null

async function signOut(): Promise<void> {
  activeUserId = null
}
```

- [ ] **Step 6: Add migration, history-limit, feedback, locale, and delete tests**

Test that 51 insertions retain entries 2 through 51, feedback updates only the selected user's entry, locale and draft survive a new repository instance with the same database name, and deleting one user leaves another user's records intact.

```ts
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"

for (let index = 0; index < 51; index += 1) {
  await repo.addHistory({
    id: `entry-${index}`,
    userId: user.id,
    profile: defaultProfile,
    job: detectedJob,
    analysis: goAnalysis,
    createdAt: new Date(index).toISOString(),
  })
}
expect((await repo.loadSnapshot()).history).toHaveLength(50)
expect((await repo.loadSnapshot()).history.map((entry) => entry.id)).not.toContain("entry-0")
```

- [ ] **Step 7: Run repository tests and type checking**

Run: `pnpm vitest run lib/web/repository.test.ts`

Then run: `pnpm typecheck`

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add package.json pnpm-lock.yaml lib/web/repository.ts lib/web/memory-repository.ts lib/web/repository.test.ts
git commit -m "feat: persist website users in indexeddb"
```

---

### Task 3: SSRF-Safe Public URL Transport

**Files:**
- Create: `lib/extraction/network.ts`
- Test: `lib/extraction/network.test.ts`

**Interfaces:**
- Consumes: Node `dns/promises`, `net`, `http`, and `https` APIs.
- Produces: `PublicPageResponse { finalUrl: string; contentType: string; body: string }`, `ExtractionNetworkError` with codes `invalid_url`, `blocked_address`, `redirect_limit`, `unsupported_content`, `response_too_large`, `timeout`, and `fetch_failed`, `isPublicAddress(address): boolean`, and `fetchPublicPage(url, dependencies?): Promise<PublicPageResponse>`.

- [ ] **Step 1: Write failing IP classification tests**

```ts
import { describe, expect, it } from "vitest"
import { isPublicAddress } from "./network"

describe("public address policy", () => {
  it.each(["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0", "::1", "fc00::1", "fe80::1"])(
    "blocks %s",
    (address) => expect(isPublicAddress(address)).toBe(false),
  )
  it.each(["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])(
    "allows %s",
    (address) => expect(isPublicAddress(address)).toBe(true),
  )
})
```

- [ ] **Step 2: Run the classification tests and confirm RED**

Run: `pnpm vitest run lib/extraction/network.test.ts`

Expected: FAIL because `network.ts` does not exist.

- [ ] **Step 3: Implement exact IPv4 and IPv6 blocked ranges**

Convert IPv4 addresses to unsigned 32-bit integers and test CIDR masks for unspecified, loopback, private, carrier-grade NAT, link-local, documentation, benchmarking, multicast, reserved, and broadcast ranges. Expand IPv4-mapped IPv6 before classification; reject IPv6 unspecified, loopback, unique-local, link-local, documentation, and multicast ranges.

```ts
const blockedV4: Array<[string, number]> = [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8],
  ["169.254.0.0", 16], ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24],
  ["192.168.0.0", 16], ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24],
  ["224.0.0.0", 4], ["240.0.0.0", 4],
]
```

- [ ] **Step 4: Write failing transport tests with injected DNS and request functions**

Cover: `file:` rejection, embedded credentials, a public HTML response, all DNS results being validated, pinned lookup returning only validated addresses, a redirect to `127.0.0.1`, more than three redirects, content type `application/octet-stream`, body over 1,000,000 bytes, and an 8-second timeout.

```ts
it("revalidates redirect targets", async () => {
  const fetchPage = createNetworkHarness({
    "https://jobs.example/start": redirect("http://127.0.0.1/private"),
  })
  await expect(fetchPublicPage("https://jobs.example/start", fetchPage.dependencies))
    .rejects.toMatchObject({ code: "blocked_address" })
})
```

- [ ] **Step 5: Implement pinned, bounded HTTP/HTTPS requests**

`fetchPublicPage` must:

```ts
const limits = { maxRedirects: 3, maxBytes: 1_000_000, timeoutMs: 8_000 }
```

For each hop, parse the URL, require `http:` or `https:`, reject username/password, resolve all addresses, reject the hop if any selected address is non-public, and pass a custom `lookup` callback to `http.request`/`https.request` that returns only the already validated addresses. Preserve the hostname for the Host header and TLS SNI. Send a fixed `User-Agent`, `Accept: text/html,text/plain`, and no caller headers. Abort on timeout or byte overflow. Resolve relative `Location` values and repeat the full validation for each redirect.

```ts
export async function fetchPublicPage(rawUrl: string, dependencies = nodeDependencies): Promise<PublicPageResponse> {
  return fetchHop(new URL(rawUrl), dependencies, 0, { maxRedirects: 3, maxBytes: 1_000_000, timeoutMs: 8_000 })
}
```

- [ ] **Step 6: Run network tests**

Run: `pnpm vitest run lib/extraction/network.test.ts`

Expected: PASS with no real network calls.

- [ ] **Step 7: Commit Task 3**

```bash
git add lib/extraction/network.ts lib/extraction/network.test.ts
git commit -m "feat: add safe public vacancy fetching"
```

---

### Task 4: Vacancy Content Extraction API

**Files:**
- Modify: `package.json`
- Modify: `pnpm-lock.yaml`
- Create: `lib/extraction/schema.ts`
- Create: `lib/extraction/content.ts`
- Create: `lib/extraction/content.test.ts`
- Create: `lib/extraction/__fixtures__/job-page.html`
- Create: `app/api/extract/handler.ts`
- Create: `app/api/extract/handler.test.ts`
- Create: `app/api/extract/route.ts`

**Interfaces:**
- Consumes: `fetchPublicPage` from Task 3 and `VacancyDraft` from Task 1.
- Produces: `extractRequestSchema`, `ExtractedVacancy`, `extractVacancyContent(page): ExtractedVacancy`, and `createExtractHandler({ fetchPage }): (request) => Promise<Response>`.

- [ ] **Step 1: Install the server-side HTML parser**

Run: `pnpm add cheerio`

Expected: `cheerio` appears in dependencies and the lockfile is updated.

- [ ] **Step 2: Add a realistic sanitized HTML fixture and failing parser tests**

The fixture contains JSON-LD `JobPosting`, Open Graph title, header/navigation noise, an `<article>` description, visible skill tags, and salary data. Assert that extraction prefers `JobPosting.title` and `description`, strips script/navigation text, deduplicates skills, parses the salary range, and caps description length at 20,000 characters. Add a plain-text test that uses the first non-empty line as title and remaining text as description.

```ts
it("prefers structured JobPosting data and removes page chrome", () => {
  const result = extractVacancyContent({ finalUrl: "https://jobs.example/42", contentType: "text/html", body: fixture })
  expect(result).toMatchObject({ title: "Senior TypeScript Engineer", hourlyRateMin: 40, hourlyRateMax: 60 })
  expect(result.description).not.toContain("Sign in")
  expect(result.skills).toEqual(["TypeScript", "React", "PostgreSQL"])
})
```

- [ ] **Step 3: Run content tests and confirm RED**

Run: `pnpm vitest run lib/extraction/content.test.ts`

Expected: FAIL because extraction code does not exist.

- [ ] **Step 4: Implement deterministic content normalization**

Use Cheerio to remove `script`, `style`, `noscript`, `nav`, `header`, `footer`, `form`, and hidden elements. Extraction precedence is:

1. valid JSON-LD `JobPosting` fields;
2. `meta[property='og:title']`, `h1`, then `<title>` for title;
3. `article`, `main`, job-description selectors, then cleaned body for description;
4. JSON-LD skills, visible skill tags, and keyword lists for skills;
5. JSON-LD base salary and visible budget patterns for optional budget fields.

Normalize whitespace, decode entities through Cheerio, remove duplicate lines, and return no fabricated values.

```ts
export function extractVacancyContent(page: PublicPageResponse): ExtractedVacancy {
  return page.contentType.startsWith("text/plain")
    ? extractPlainText(page.body, page.finalUrl)
    : extractHtml(load(page.body), page.finalUrl)
}
```

- [ ] **Step 5: Write failing handler tests**

Test invalid JSON, invalid URL, successful HTML extraction, insufficient extracted description returning `422 extraction_insufficient`, and every `ExtractionNetworkError` code mapping to a stable HTTP status and JSON error code.

```ts
it("returns a manual-entry fallback for insufficient content", async () => {
  const handler = createExtractHandler({ fetchPage: async () => ({ finalUrl: "https://example.com", contentType: "text/html", body: "<h1>Role</h1>" }) })
  const response = await handler(extractRequest("https://example.com"))
  expect(response.status).toBe(422)
  await expect(response.json()).resolves.toEqual({ error: "extraction_insufficient" })
})
```

- [ ] **Step 6: Implement the route handler**

`POST /api/extract` accepts `{ url: string }`, limits the JSON body to 5,000 characters, calls the injected fetch function, returns the normalized draft, and never returns raw remote HTML. `app/api/extract/route.ts` exports `runtime = "nodejs"` and delegates to the handler with `fetchPublicPage`.

```ts
export const runtime = "nodejs"
const handler = createExtractHandler({ fetchPage: fetchPublicPage })
export async function POST(request: Request) { return handler(request) }
```

- [ ] **Step 7: Run extraction tests and type checking**

Run: `pnpm vitest run lib/extraction app/api/extract`

Then run: `pnpm typecheck`

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add package.json pnpm-lock.yaml lib/extraction app/api/extract
git commit -m "feat: extract vacancies from public urls"
```

---

### Task 5: Real Website Analysis Client and API Error Contract

**Files:**
- Create: `lib/web/api.ts`
- Create: `lib/web/api.test.ts`
- Create: `lib/web/history.ts`
- Create: `lib/web/history.test.ts`
- Modify: `lib/analysis/prompt.ts`
- Modify: `lib/analysis/prompt.test.ts`
- Modify: `app/api/analyze/handler.ts`
- Modify: `app/api/analyze/route.ts`
- Modify: `app/api/analyze/route.test.ts`

**Interfaces:**
- Consumes: `/api/extract`, `/api/analyze`, `VacancyDraft`, `AnalysisRequest`, and `WebsiteRepository` records.
- Produces: `WebApiError` with stable codes, `WebsiteApi { extractVacancy(url): Promise<VacancyDraft>; analyzeVacancy(request): Promise<FitAnalysis> }`, the production `websiteApi`, `draftToJob(draft): Job`, `createHistoryEntry(input): WebHistoryEntry`, and `toCalibrationMemory(history): CalibrationEntry[]`.

- [ ] **Step 1: Write failing browser API tests**

Stub `fetch` and assert that `extractVacancy` posts only `{ url }`, `analyzeVacancy` posts the validated request, non-2xx error payloads become `WebApiError` codes, malformed success JSON becomes `invalid_response`, and an `AbortError` becomes `network_error`.

```ts
it("maps a stable extraction error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ error: "blocked_address" }, { status: 403 })))
  await expect(extractVacancy("http://127.0.0.1/job"))
    .rejects.toMatchObject({ code: "blocked_address" })
})
```

- [ ] **Step 2: Run API client tests and confirm RED**

Run: `pnpm vitest run lib/web/api.test.ts`

Expected: FAIL because `api.ts` does not exist.

- [ ] **Step 3: Implement the typed browser client and draft conversion**

Use same-origin relative URLs, `content-type: application/json`, and schema validation before returning. `draftToJob` keeps `url` absent for manual text and creates `id` from `crypto.randomUUID()` without inventing a source URL.

```ts
export async function analyzeVacancy(request: AnalysisRequest): Promise<FitAnalysis> {
  const response = await fetch("/api/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  })
  return parseApiResponse(response, fitAnalysisSchema)
}
```

- [ ] **Step 4: Add history projection tests and implementation**

Assert that history stores both profile and vacancy snapshots, sorts newest first, and maps only the newest ten entries to `{ jobTitle, predictedScore, correctedScore?, note? }`.

```ts
const history = Array.from({ length: 12 }, (_, index) => ({
  ...baseHistoryEntry,
  id: `entry-${index}`,
  createdAt: new Date(index).toISOString(),
}))
expect(toCalibrationMemory(history)).toHaveLength(10)
expect(createHistoryEntry({ userId, profile, job, analysis, now })).toMatchObject({
  userId,
  profile,
  job,
  analysis,
})
```

- [ ] **Step 5: Harden the prompt boundary for arbitrary websites**

Replace Upwork-specific wording with “public job vacancy.” Wrap vacancy content in explicit markers:

```text
BEGIN UNTRUSTED VACANCY CONTENT
...
END UNTRUSTED VACANCY CONTENT
```

The system instructions state that commands contained inside those markers are vacancy data and must never override scoring or output instructions. Extend prompt tests with a vacancy description containing “ignore previous instructions.”

- [ ] **Step 6: Update analysis origin and configuration tests**

Add cases for the configured website origin, missing `OPENROUTER_API_KEY` returning `503 server_not_configured`, and same-origin POST behavior. Retain explicit allowlist rejection for cross-origin requests.

```ts
it("accepts the website's same origin", async () => {
  const response = await handler(request(validBody, "http://localhost:3000"))
  expect(response.status).toBe(200)
})

it("reports missing server configuration", async () => {
  vi.stubEnv("OPENROUTER_API_KEY", "")
  expect((await POST(request(validBody))).status).toBe(503)
})
```

- [ ] **Step 7: Implement the updated handler contract**

Pass the request URL origin into origin validation. Accept when `Origin` equals the request origin or appears in `ALLOWED_ORIGINS`; reject other explicit origins. Return localized-independent stable codes from the server and let the browser translate them.

```ts
const requestOrigin = new URL(request.url).origin
const origin = request.headers.get("origin")
if (origin && origin !== requestOrigin && !options.allowedOrigins.includes(origin)) {
  return json({ error: "origin_not_allowed" }, 403)
}
```

- [ ] **Step 8: Run analysis, client, and history tests**

Run: `pnpm vitest run lib/web/api.test.ts lib/web/history.test.ts lib/analysis app/api/analyze`

Expected: PASS and no mock response in production code.

- [ ] **Step 9: Commit Task 5**

```bash
git add lib/web/api.ts lib/web/api.test.ts lib/web/history.ts lib/web/history.test.ts lib/analysis/prompt.ts lib/analysis/prompt.test.ts app/api/analyze
git commit -m "feat: connect website to real vacancy analysis"
```

---

### Task 6: Typed Website Localization, Local Login, and Responsive Shell

**Files:**
- Create: `lib/i18n/web-messages.ts`
- Create: `lib/i18n/web-messages.test.ts`
- Create: `components/web/language-switch.tsx`
- Create: `components/web/auth-screen.tsx`
- Create: `components/web/app-shell.tsx`
- Create: `components/web/website-app.tsx`
- Create: `components/web/website-app.test.tsx`
- Modify: `app/page.tsx`
- Modify: `app/layout.tsx`

**Interfaces:**
- Consumes: `WebsiteRepository`, `createWebsiteRepository`, `LocalAuthError`, and `Locale`.
- Produces: `WebMessages`, `getWebMessages(locale)`, and `<WebsiteApp repository? api?>` where omitted props instantiate production IndexedDB and HTTP adapters.

- [ ] **Step 1: Write failing localization parity tests**

```ts
import { describe, expect, it } from "vitest"
import { webMessages } from "./web-messages"

describe("website messages", () => {
  it("keeps Russian and English dictionaries structurally identical", () => {
    expect(Object.keys(webMessages.ru).sort()).toEqual(Object.keys(webMessages.en).sort())
  })
})
```

Include concrete keys for authentication, navigation, profile, URL/text modes, review, analysis, result, history, feedback, destructive confirmations, and every `WebApiError` and `LocalAuthError` code.

- [ ] **Step 2: Write failing authentication and locale component tests**

Render `<WebsiteApp>` with `createMemoryWebsiteRepository()`. Test account creation from empty storage, the browser-only account notice, session restoration on a second render, wrong-password feedback, sign-out returning to sign-in, and RU/EN switching changing “New analysis” to “Новый анализ” without remounting the app.

```tsx
it("creates a remembered local account and switches language", async () => {
  const repository = createMemoryWebsiteRepository()
  const apiStub: WebsiteApi = {
    extractVacancy: vi.fn(),
    analyzeVacancy: vi.fn(),
  }
  render(<WebsiteApp repository={repository} api={apiStub} />)
  await userEvent.type(screen.getByLabelText("Name"), "Nikita")
  await userEvent.type(screen.getByLabelText("Email"), "me@example.com")
  await userEvent.type(screen.getByLabelText("Password"), "password-123")
  await userEvent.click(screen.getByRole("button", { name: "Create account" }))
  await userEvent.click(screen.getByRole("button", { name: "RU" }))
  expect(await screen.findByText("Новый анализ")).toBeVisible()
})
```

- [ ] **Step 3: Run component tests and confirm RED**

Run: `pnpm vitest run lib/i18n/web-messages.test.ts components/web/website-app.test.tsx`

Expected: FAIL because the web components do not exist.

- [ ] **Step 4: Implement typed messages and locale persistence**

Initialize an unauthenticated locale from `localStorage.getItem("fitcheck.locale")` or `resolveLocale(navigator.language)`. Persist changes immediately to localStorage; after authentication also call `repository.saveLocale(user.id, locale)`.

```ts
function initialLocale(): Locale {
  const stored = localStorage.getItem("fitcheck.locale")
  return stored === "ru" || stored === "en" ? stored : resolveLocale(navigator.language)
}
```

- [ ] **Step 5: Implement authentication screen and shell**

`AuthScreen` has accessible tabs/buttons for Create account and Sign in, labeled inputs, disabled submit during work, typed inline errors, and the explicit local-only notice. `AppShell` provides New Analysis, History, Profile, locale switch, current display name, and sign out; use a desktop header and an accessible compact mobile navigation.

```tsx
<AppShell
  activeView={view}
  user={snapshot.user}
  locale={locale}
  onNavigate={setView}
  onLocaleChange={changeLocale}
  onSignOut={signOut}
>
  {renderView()}
</AppShell>
```

- [ ] **Step 6: Replace the mock preview entry point**

`app/page.tsx` becomes:

```tsx
"use client"

import { WebsiteApp } from "@/components/web/website-app"

export default function Page() {
  return <WebsiteApp />
}
```

Update metadata from Upwork-extension wording to public-vacancy website wording. Do not import preview runtime or mock data.

- [ ] **Step 7: Run authentication tests and production-path import check**

Run: `pnpm vitest run lib/i18n/web-messages.test.ts components/web/website-app.test.tsx`

Then run: `rg 'mock-data|preview-adapter' app components/web lib/web`

Expected: tests PASS and `rg` exits 1 because it finds no production imports.

- [ ] **Step 8: Commit Task 6**

```bash
git add app/page.tsx app/layout.tsx components/web lib/i18n/web-messages.ts lib/i18n/web-messages.test.ts
git commit -m "feat: add local login and website shell"
```

---

### Task 7: Profile, Vacancy Source Selection, and Editable Review

**Files:**
- Create: `components/web/profile-editor.tsx`
- Create: `components/web/profile-editor.test.tsx`
- Create: `components/web/vacancy-source.tsx`
- Create: `components/web/vacancy-source.test.tsx`
- Create: `components/web/vacancy-review.tsx`
- Modify: `components/web/website-app.tsx`
- Modify: `components/web/website-app.test.tsx`

**Interfaces:**
- Consumes: active user/snapshot, repository `saveProfile` and `saveDraft`, API `extractVacancy`, `freelancerProfileSchema`, and `vacancyDraftSchema`.
- Produces: validated `FreelancerProfile`, source mode state, persisted `VacancyDraft`, and transitions `source -> review -> analyzing` plus `review -> source` with preserved draft.

- [ ] **Step 1: Write failing profile-flow tests**

Test that a user with no profile sees profile setup before New Analysis; specialization and at least one skill are required; numeric fields obey schema bounds; saving shows the source-selection screen; editing the profile later does not mutate profile snapshots in history.

```tsx
it("requires a real profile before vacancy analysis", async () => {
  const repository = createMemoryWebsiteRepository()
  await repository.createUser({ name: "Nikita", email: "me@example.com", password: "password-123" })
  render(<WebsiteApp repository={repository} api={apiStub} />)
  expect(await screen.findByRole("heading", { name: "Create your freelancer profile" })).toBeVisible()
  expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled()
})
```

- [ ] **Step 2: Write failing source and back-navigation tests**

Test URL mode posts a public URL and displays the extracted editable fields, text mode accepts a title and description without a URL, switching modes preserves both form buffers, extraction failure shows its typed message plus “Paste text instead,” and review's “Back to vacancy selection” returns with values intact.

```tsx
it("returns to source selection with the draft preserved", async () => {
  await enterManualVacancy(user, { title: "Backend role", description: "Build production APIs for a SaaS platform." })
  await user.click(screen.getByRole("button", { name: "Review vacancy" }))
  await user.click(screen.getByRole("button", { name: "Back to vacancy selection" }))
  expect(screen.getByLabelText("Vacancy title")).toHaveValue("Backend role")
})
```

- [ ] **Step 3: Run focused component tests and confirm RED**

Run: `pnpm vitest run components/web/profile-editor.test.tsx components/web/vacancy-source.test.tsx components/web/website-app.test.tsx`

Expected: FAIL because the workflow components are missing.

- [ ] **Step 4: Implement the profile editor**

Reuse focused UI primitives and `SkillInput` behavior, but render a website-width form. Validate with `freelancerProfileSchema.safeParse`; show field-level messages and keep raw values on failure. Start new users with empty specialization/skills, `0` years, `0` rate, and `Intermediate` English rather than `defaultProfile`.

```ts
const emptyProfile: FreelancerProfile = {
  specialization: "",
  skills: [],
  experienceYears: 0,
  preferredRate: 0,
  englishLevel: "Intermediate",
}
```

- [ ] **Step 5: Implement source selection with two persistent buffers**

Keep `{ url }` and `{ title, description, skills, budget, sourceUrl }` in separate state objects. URL submit calls `api.extractVacancy`; text submit normalizes directly. Disable only the active submit action while loading. Save the normalized draft before moving to review.

```ts
const [urlInput, setUrlInput] = useState("")
const [textInput, setTextInput] = useState<ManualVacancyInput>(emptyManualVacancy)
const [sourceMode, setSourceMode] = useState<VacancySourceMode>("url")
```

- [ ] **Step 6: Implement editable vacancy review**

Expose title, description, comma-separated skills, optional hourly min/max, fixed budget, and source URL. Validate on Analyze. Back saves the current draft and returns to the source step. Analysis submission passes the active profile, converted job, active locale, and calibration memory to the API.

```ts
async function returnToSource(nextDraft: VacancyDraft) {
  await repository.saveDraft(user.id, nextDraft)
  setDraft(nextDraft)
  setAnalysisStep("source")
}
```

- [ ] **Step 7: Run workflow tests**

Run: `pnpm vitest run components/web/profile-editor.test.tsx components/web/vacancy-source.test.tsx components/web/website-app.test.tsx`

Expected: PASS for both input methods and preserved back navigation.

- [ ] **Step 8: Commit Task 7**

```bash
git add components/web/profile-editor.tsx components/web/profile-editor.test.tsx components/web/vacancy-source.tsx components/web/vacancy-source.test.tsx components/web/vacancy-review.tsx components/web/website-app.tsx components/web/website-app.test.tsx
git commit -m "feat: add real vacancy input workflow"
```

---

### Task 8: Analysis Result, Feedback, and Persistent History

**Files:**
- Create: `components/web/analysis-result.tsx`
- Create: `components/web/analysis-result.test.tsx`
- Create: `components/web/history-view.tsx`
- Create: `components/web/history-view.test.tsx`
- Modify: `components/web/website-app.tsx`
- Modify: `components/web/website-app.test.tsx`

**Interfaces:**
- Consumes: real API analysis result, `createHistoryEntry`, `repository.addHistory`, `saveFeedback`, `clearHistory`, and existing score/detail primitives where their presentation is website-appropriate.
- Produces: result/detail/feedback UI, history navigation, `result -> source` transitions, and persisted calibration corrections.

- [ ] **Step 1: Write failing analysis-state tests**

Test meaningful progress during a pending API promise, a successful score and GO/NO-GO result, no history write before success, one history write after success, typed retry UI on failure with the review draft retained, and “Analyze another vacancy” returning to source selection.

```tsx
function createDeferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

async function submitReviewedVacancy(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Paste text" }))
  await user.type(screen.getByLabelText("Vacancy title"), "Senior TypeScript Engineer")
  await user.type(screen.getByLabelText("Vacancy description"), "Build and maintain a production SaaS platform using TypeScript and PostgreSQL.")
  await user.click(screen.getByRole("button", { name: "Review vacancy" }))
  await user.click(screen.getByRole("button", { name: "Analyze vacancy" }))
}

it("persists history only after a validated analysis", async () => {
  const deferred = createDeferred<FitAnalysis>()
  const repository = createMemoryWebsiteRepository()
  const user = await repository.createUser({ name: "Nikita", email: "me@example.com", password: "password-123" })
  await repository.saveProfile(user.id, defaultProfile)
  const api: WebsiteApi = { extractVacancy: vi.fn(), analyzeVacancy: () => deferred.promise }
  render(<WebsiteApp repository={repository} api={api} />)
  await submitReviewedVacancy(userEvent.setup())
  expect((await repository.loadSnapshot()).history).toHaveLength(0)
  deferred.resolve(goAnalysis)
  expect(await screen.findByLabelText("Fit score 82 out of 100")).toBeVisible()
  expect((await repository.loadSnapshot()).history).toHaveLength(1)
})
```

- [ ] **Step 2: Write failing result and history tests**

Assert score accessible text, localized summary/strengths/risks, five breakdown values, correction score 0–100 plus optional note, reopening a history entry, newest-first display, explicit confirmation before clear, and “Back to vacancy selection” from an opened result.

```tsx
it("reopens a persisted result and saves a correction", async () => {
  const entry: WebHistoryEntry = {
    id: "entry-1",
    userId: "user-1",
    profile: defaultProfile,
    job: detectedJob,
    analysis: goAnalysis,
    createdAt: "2026-08-25T12:00:00.000Z",
  }
  render(<HistoryView entries={[entry]} onOpen={onOpen} copy={webMessages.en} />)
  await userEvent.click(screen.getByRole("button", { name: /Senior TypeScript Engineer/ }))
  expect(onOpen).toHaveBeenCalledWith(entry)
})
```

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `pnpm vitest run components/web/analysis-result.test.tsx components/web/history-view.test.tsx components/web/website-app.test.tsx`

Expected: FAIL because result/history components are missing.

- [ ] **Step 4: Implement successful and failed analysis transitions**

On success, snapshot the current profile and job, persist the entry, update in-memory history, then render the result. On failure, retain review state and expose Retry and Edit vacancy. Never write history in `catch` or before response validation.

```ts
try {
  const analysis = await api.analyzeVacancy(request)
  const entry = createHistoryEntry({ userId: user.id, profile, job: request.job, analysis, now: new Date() })
  await repository.addHistory(entry)
  setHistory((current) => [entry, ...current].slice(0, 50))
  setActiveEntry(entry)
  setAnalysisStep("result")
} catch (error) {
  setAnalysisError(toWebApiError(error))
  setAnalysisStep("review")
}
```

- [ ] **Step 5: Implement website result and feedback UI**

Use a wide two-column result on desktop: decision/summary and breakdown on the left, strengths/risks on the right; stack on mobile. Provide visible Back to vacancy selection and Analyze another vacancy actions. Feedback saves a corrected integer score and trimmed optional note without modifying the original analysis.

```tsx
<div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(20rem,0.9fr)]">
  <DecisionAndBreakdown entry={entry} copy={copy} />
  <StrengthsAndRisks analysis={entry.analysis} copy={copy} />
</div>
```

- [ ] **Step 6: Implement history navigation and deletion**

Render newest-first cards with title, score, status, and localized date. Opening a card renders its immutable snapshots. Clear history only after `window.confirm(copy.clearHistoryConfirmation)` returns true; account deletion uses a different confirmation and calls `deleteUser`.

```ts
async function clearHistory() {
  if (!window.confirm(copy.clearHistoryConfirmation)) return
  await repository.clearHistory(user.id)
  setHistory([])
}
```

- [ ] **Step 7: Run result/history tests and all web tests**

Run: `pnpm vitest run components/web lib/web lib/i18n`

Expected: PASS.

- [ ] **Step 8: Commit Task 8**

```bash
git add components/web/analysis-result.tsx components/web/analysis-result.test.tsx components/web/history-view.tsx components/web/history-view.test.tsx components/web/website-app.tsx components/web/website-app.test.tsx
git commit -m "feat: persist website analysis history"
```

---

### Task 9: Responsive Visual Polish, Documentation, and Full Verification

**Files:**
- Modify: `app/globals.css`
- Modify: `app/layout.tsx`
- Modify: `components/web/app-shell.tsx`
- Modify: `components/web/auth-screen.tsx`
- Modify: `components/web/profile-editor.tsx`
- Modify: `components/web/vacancy-source.tsx`
- Modify: `components/web/vacancy-review.tsx`
- Modify: `components/web/analysis-result.tsx`
- Modify: `components/web/history-view.tsx`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: tests affected by final accessibility adjustments

**Interfaces:**
- Consumes: all completed website flows and API configuration.
- Produces: presentation-ready desktop/mobile site, accurate setup documentation, and final verification evidence.

- [ ] **Step 1: Add failing accessibility and responsive assertions**

Extend component tests to assert one `main` landmark, labeled navigation, associated labels for every field, visible focusable back actions, live regions for loading/errors, accessible names for scores, and absence of fixed `h-[600px]`/`w-[400px]` classes in website components.

```tsx
expect(screen.getAllByRole("main")).toHaveLength(1)
expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeVisible()
expect(screen.getByRole("status")).toHaveTextContent("Analyzing vacancy")
expect(document.querySelector('[class*="w-[400px]"]')).toBeNull()
```

- [ ] **Step 2: Run the final UI tests and confirm RED where gaps exist**

Run: `pnpm vitest run components/web`

Expected: one or more new accessibility assertions fail before polish.

- [ ] **Step 3: Apply the responsive visual system**

Use a full-width page background, a `max-w-7xl` application shell, 12-column desktop grids where useful, readable `max-w-3xl` forms, and single-column mobile layouts below the Tailwind `md` breakpoint. Keep primary actions visually dominant, preserve visible keyboard focus, and use existing success/warning/danger tokens for score states. Remove extension-only dimensions from the production path.

```tsx
<main className="min-h-svh bg-background">
  <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    {children}
  </div>
</main>
```

- [ ] **Step 4: Update documentation and environment examples**

Rewrite README product/run sections around the website. Document:

- local-only accounts and IndexedDB persistence;
- real text and public-URL vacancy inputs;
- best-effort extraction and manual fallback;
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and `ALLOWED_ORIGINS`;
- `pnpm dev`, verification commands, and the lack of server user storage.

Update `.env.example` to use website origins and remove `WXT_PUBLIC_API_BASE_URL` from the primary website setup while leaving extension-specific configuration clearly separated if it remains needed by untouched extension builds.

```dotenv
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openrouter/free
ALLOWED_ORIGINS=http://localhost:3000

# Legacy extension build only
WXT_PUBLIC_API_BASE_URL=http://localhost:3000
```

- [ ] **Step 5: Run the complete automated verification**

Run:

```bash
pnpm test
pnpm typecheck
pnpm lint
pnpm build:web
```

Expected: all commands exit 0; production build exposes `/`, `/api/analyze`, and `/api/extract` without TypeScript or lint errors.

- [ ] **Step 6: Start the production website and complete manual acceptance**

Run: `pnpm dev`

With a real server-side key, verify this exact sequence in desktop and mobile viewports: create user, create profile, paste a real vacancy, analyze, return to source, import a public URL, edit and analyze, open both history entries, switch RU/EN mid-form, reload, sign out, sign back in, and confirm data persistence. Also verify a blocked URL falls back to manual paste and a missing key shows `server_not_configured` copy rather than a mock score.

- [ ] **Step 7: Inspect repository state and commit final integration**

Run: `git diff --check`

Then run: `git status --short`

Expected: no whitespace errors and only intentional website files changed.

```bash
git add app README.md .env.example components/web lib/web lib/i18n/web-messages.ts lib/i18n/web-messages.test.ts package.json pnpm-lock.yaml
git commit -m "feat: deliver testable FitCheck website"
```
