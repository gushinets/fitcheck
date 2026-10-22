import { expect, test, type Page } from "@playwright/test"
import { derivePassword } from "../lib/web/password"
import { defaultProfile, detectedJob, goAnalysis } from "../lib/mock-data"

const password = "correct horse battery staple"
async function register(page: Page, email: string) {
  await page.goto("/")
  await page.getByLabel("Email", { exact: true }).fill(email)
  await page.getByLabel("Password", { exact: true }).fill(password)
  await page.getByRole("button", { name: "Create account", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible()
  const mail = await page.request.get(`http://127.0.0.1:38154/testing/mail?email=${encodeURIComponent(email)}`)
  await page.getByLabel("Verification code").fill((await mail.json()).token)
  await page.getByRole("button", { name: "Verify", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Complete your freelancer profile" })).toBeVisible()
}
async function profile(page: Page) {
  await page.getByLabel("Specialization", { exact: true }).fill("Frontend Developer")
  await page.getByPlaceholder("Type a skill and press Enter").fill("React")
  await page.getByPlaceholder("Type a skill and press Enter").press("Enter")
  await page.getByRole("checkbox", { name: "Remote", exact: true }).check()
  await page.getByRole("button", { name: "Save profile", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Choose how to add a task" })).toBeVisible()
}
async function task(page: Page, title: string) {
  await page.getByRole("button", { name: "Paste text", exact: true }).click()
  await page.getByLabel("Task title", { exact: true }).fill(title)
  await page.getByLabel("Task description", { exact: true }).fill("Build a React application with TypeScript and accessible forms for customers.")
  await page.getByRole("button", { name: "Review task", exact: true }).click()
  await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/v1/analysis-jobs") && response.request().method() === "POST"),
    page.getByRole("button", { name: "Analyze task", exact: true }).click(),
  ])
}
async function login(page: Page, email: string) {
  await page.goto("/")
  await page.getByRole("button", { name: "Switch to sign in" }).click()
  await page.getByLabel("Email", { exact: true }).fill(email)
  await page.getByLabel("Password", { exact: true }).fill(password)
  await page.getByRole("button", { name: "Sign in", exact: true }).click()
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible()
}

test("demo → verified account → claim → analysis survives reload → second browser history → ownership isolation", async ({ page, browser }) => {
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  await page.goto("/")
  await page.getByRole("button", { name: "Try without an account" }).click()
  await expect(page.getByRole("heading", { name: "Complete your freelancer profile" })).toBeVisible()
  await profile(page)
  await task(page, "Demo React task")
  await expect(page.getByText("Demo React task", { exact: true })).toBeVisible({ timeout: 15_000 })
  await page.getByRole("button", { name: "Create account / sign in" }).click()
  const email = `e2e-${Date.now()}@example.com`
  await register(page, email)
  await page.getByRole("button", { name: "Save demo to account" }).click()
  await expect(page.getByText("Demo saved to your account.")).toBeVisible()
  await page.getByRole("button", { name: "New analysis", exact: true }).first().click()
  await task(page, "Persisted React task")
  await page.reload()
  await expect(page.getByText("Persisted React task", { exact: true })).toBeVisible({ timeout: 15_000 })
  const result = await page.request.get("/api/backend/v1/history?limit=100")
  const items = (await result.json()).items
  expect(items).toHaveLength(2)
  const analysisId = items.find((entry: { snapshot: { vacancy: { title: string } } }) => entry.snapshot.vacancy.title === "Persisted React task").analysisId
  const otherDevice = await browser.newContext()
  const other = await otherDevice.newPage()
  await login(other, email)
  await other.getByRole("button", { name: "History", exact: true }).first().click()
  await expect(other.getByRole("button", { name: /Persisted React task/ })).toBeVisible()
  await expect(other.getByRole("button", { name: /Demo React task/ })).toBeVisible()
  await other.getByLabel("Application status: Persisted React task").selectOption("applied")
  await expect(other.getByLabel("Application status: Persisted React task")).toHaveValue("applied")
  const strangerContext = await browser.newContext()
  const stranger = await strangerContext.newPage()
  await register(stranger, `stranger-${Date.now()}@example.com`)
  expect((await stranger.request.get(`/api/backend/v1/analyses/${analysisId}`)).status()).toBe(404)
  expect((await stranger.request.get("/api/backend/v1/history")).ok()).toBe(true)
  expect((await (await stranger.request.get("/api/backend/v1/history")).json()).items).toEqual([])
  await otherDevice.close(); await strangerContext.close()
  expect(errors).toEqual([])
})

test("legacy import retries preserve server records and do not duplicate history", async ({ page }) => {
  await register(page, `import-${Date.now()}@example.com`)
  const oldEmail = "legacy@example.com"
  const digest = await derivePassword(password)
  await page.evaluate(async ({ oldEmail, digest, defaultProfile, detectedJob, goAnalysis }) => {
    const opened = indexedDB.open("fitcheck-web", 1)
    opened.onupgradeneeded = () => {
      const db = opened.result
      db.createObjectStore("users", { keyPath: "id" }).createIndex("email", "email", { unique: true })
      db.createObjectStore("profiles", { keyPath: "userId" })
      db.createObjectStore("preferences", { keyPath: "userId" })
      db.createObjectStore("drafts", { keyPath: "userId" })
      db.createObjectStore("history", { keyPath: "id" }).createIndex("userId", "userId")
      db.createObjectStore("meta", { keyPath: "key" })
    }
    const db = await new Promise<IDBDatabase>((resolve, reject) => { opened.onsuccess = () => resolve(opened.result); opened.onerror = () => reject(opened.error) })
    const transaction = db.transaction(["users", "profiles", "history"], "readwrite")
    const userId = crypto.randomUUID()
    const createdAt = new Date().toISOString()
    transaction.objectStore("users").put({ id: userId, name: "Legacy", email: oldEmail, createdAt, password: digest })
    transaction.objectStore("profiles").put({ userId, profile: defaultProfile })
    const job = { ...detectedJob, title: "Imported legacy task" }
    delete job.url
    transaction.objectStore("history").put({ id: crypto.randomUUID(), userId, profile: null, createdAt, job, analysis: goAnalysis })
    await new Promise<void>((resolve, reject) => { transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error) })
    db.close()
  }, { oldEmail, digest, defaultProfile, detectedJob, goAnalysis })
  await page.getByLabel("Local account email").fill(oldEmail)
  await page.getByLabel("Local account password").fill(password)
  await page.getByRole("button", { name: "Import / retry" }).click()
  await expect(page.getByText("Imported: 1; skipped: 0; conflicts: 0; invalid: 0.")).toBeVisible({ timeout: 15_000 })
  await page.getByLabel("Local account password").fill(password)
  await page.getByRole("button", { name: "Import / retry" }).click()
  await expect(page.getByText("Imported: 1; skipped: 0; conflicts: 0; invalid: 0.")).toBeVisible({ timeout: 15_000 })
  await page.getByRole("button", { name: "History", exact: true }).first().click()
  await expect(page.getByRole("link", { name: "Task URL" })).toHaveCount(0)
  await page.getByRole("button", { name: /Imported legacy task/ }).click()
  await expect(page.getByText("Imported legacy task", { exact: true })).toBeVisible()
  const history = await (await page.request.get("/api/backend/v1/history")).json()
  expect(history.items).toHaveLength(1)
  expect(history.items[0].snapshot.profile).toBeNull()
  expect(history.items[0].snapshot.vacancy).not.toHaveProperty("url")
})

test("URL survives extraction, review, publication and reload; manual tasks have no source action", async ({ page, context }) => {
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  const sourceUrl = "https://tasks.example.test/projects/n8n/task?ref=history#details"
  await register(page, `source-link-${Date.now()}@example.com`)
  await profile(page)
  await page.getByLabel("Task URL", { exact: true }).fill(sourceUrl)
  await page.getByRole("button", { name: "Load task", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Review the task" })).toBeVisible()
  await page.getByLabel("Task title", { exact: true }).fill("Reviewed n8n task")
  await page.getByRole("button", { name: "Analyze task", exact: true }).click()
  await expect(page.getByText("Reviewed n8n task", { exact: true })).toBeVisible({ timeout: 15_000 })
  await page.reload()
  await page.getByRole("button", { name: "History", exact: true }).first().click()
  const source = page.getByRole("link", { name: "Task URL", exact: true })
  await expect(source).toHaveAttribute("href", sourceUrl)
  await expect(source).toHaveAttribute("target", "_blank")
  await expect(source).toHaveAttribute("rel", /noopener/)
  await expect(source).toHaveAttribute("rel", /noreferrer/)
  const saved = await (await page.request.get("/api/backend/v1/history?limit=100")).json()
  expect(saved.items).toHaveLength(1)
  expect(saved.items[0].snapshot.vacancy.url).toBe(sourceUrl)

  // Resolve the external destination locally while exercising a real new tab.
  await context.route("https://tasks.example.test/**", route => route.fulfill({ contentType: "text/html", body: "<title>Original task</title><p>Original task</p>" }))
  const opened = context.waitForEvent("page")
  await source.click()
  const original = await opened
  await expect(original).toHaveURL(sourceUrl)
  expect(await original.evaluate(() => window.opener === null)).toBe(true)
  expect(await original.evaluate(() => document.referrer)).toBe("")
  await original.close()
  await expect(page.getByRole("heading", { name: "Analysis history" })).toBeVisible()

  await page.getByRole("button", { name: "New analysis", exact: true }).first().click()
  await task(page, "Manual task without URL")
  await expect(page.getByText("Manual task without URL", { exact: true })).toBeVisible({ timeout: 15_000 })
  await page.reload()
  await page.getByRole("button", { name: "History", exact: true }).first().click()
  await expect(source).toHaveCount(1)
  const history = await (await page.request.get("/api/backend/v1/history?limit=100")).json()
  expect(history.items).toHaveLength(2)
  expect(history.items.find((item: { snapshot: { vacancy: { title: string } } }) => item.snapshot.vacancy.title === "Manual task without URL").snapshot.vacancy).not.toHaveProperty("url")
  await page.getByRole("button", { name: /Manual task without URL/ }).click()
  await expect(page.getByText("Manual task without URL", { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})
