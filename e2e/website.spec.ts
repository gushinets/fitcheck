import { expect, test, type Page } from "@playwright/test"
import { derivePassword } from "../lib/web/password"
import { defaultProfile, detectedJob, goAnalysis } from "../lib/mock-data"
import { webMessages } from "../lib/i18n/web-messages"
import type { Locale } from "../lib/types"

const password = "correct horse battery staple"
async function register(page: Page, email: string, locale: Locale = "en") {
  const copy = webMessages[locale]
  await page.goto("/")
  if (locale === "ru") await page.getByRole("button", { name: "RU", exact: true }).click()
  await page.getByLabel(copy.email, { exact: true }).fill(email)
  await page.getByLabel(copy.password, { exact: true }).fill(password)
  await page.getByRole("button", { name: copy.createAccount, exact: true }).click()
  await expect(page.getByRole("heading", { name: locale === "ru" ? "Подтвердите email" : "Verify your email" })).toBeVisible()
  const mail = await page.request.get(`http://127.0.0.1:38154/testing/mail?email=${encodeURIComponent(email)}`)
  await page.getByLabel(locale === "ru" ? "Код подтверждения" : "Verification code").fill((await mail.json()).token)
  await page.getByRole("button", { name: locale === "ru" ? "Подтвердить" : "Verify", exact: true }).click()
  await expect(page.getByRole("heading", { name: copy.completeProfileTitle })).toBeVisible()
}
async function profile(page: Page, locale: Locale = "en") {
  const copy = webMessages[locale]
  await page.getByLabel(copy.specialization, { exact: true }).fill("Frontend Developer")
  await page.getByPlaceholder(copy.skillsPlaceholder).fill("React")
  await page.getByPlaceholder(copy.skillsPlaceholder).press("Enter")
  await page.getByLabel(copy.preferredRate, { exact: true }).fill("65")
  await page.getByRole("checkbox", { name: copy.workRemote, exact: true }).check()
  await page.getByRole("button", { name: copy.saveProfile, exact: true }).click()
  await expect(page.getByRole("heading", { name: copy.chooseVacancyTitle })).toBeVisible()
}
async function task(page: Page, title: string, locale: Locale = "en") {
  const copy = webMessages[locale]
  await page.getByRole("button", { name: copy.pasteText, exact: true }).click()
  await page.getByLabel(copy.vacancyTitle, { exact: true }).fill(title)
  await page.getByLabel(copy.vacancyDescription, { exact: true }).fill("Build a React application with TypeScript and accessible forms for customers.")
  await page.getByRole("button", { name: copy.reviewVacancy, exact: true }).click()
  const [admission] = await Promise.all([
    page.waitForResponse(response => response.url().endsWith("/v1/analysis-jobs") && response.request().method() === "POST"),
    page.getByRole("button", { name: copy.analyzeVacancy, exact: true }).click(),
  ])
  return admission.json() as Promise<{ jobId: string }>
}
async function login(page: Page, email: string, locale: Locale = "en") {
  const copy = webMessages[locale]
  await page.goto("/")
  if (locale === "ru") await page.getByRole("button", { name: "RU", exact: true }).click()
  await page.getByRole("button", { name: copy.switchToSignIn }).click()
  await page.getByLabel(copy.email, { exact: true }).fill(email)
  await page.getByLabel(copy.password, { exact: true }).fill(password)
  await page.getByRole("button", { name: copy.signIn, exact: true }).click()
  await expect(page.getByRole("button", { name: copy.signOut, exact: true })).toBeVisible()
}

for (const locale of ["en", "ru"] as const) test(`demo → claim recovery → second browser profile/history (${locale})`, async ({ page, browser }) => {
  const copy = webMessages[locale]
  const ru = locale === "ru"
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  await page.goto("/")
  if (ru) await page.getByRole("button", { name: "RU", exact: true }).click()
  await page.getByRole("button", { name: copy.tryDemo }).click()
  await expect(page.getByText(ru ? "Лимит демо — один анализ. После подтверждения email результат можно сохранить в аккаунт." : "The demo allows one analysis. Verify your email to save the result to your account.")).toBeVisible()
  await expect(page.getByRole("heading", { name: copy.completeProfileTitle })).toBeVisible()
  await profile(page, locale)
  const demo = await task(page, "Demo React task", locale)
  await expect(page.getByText("Demo React task", { exact: true })).toBeVisible({ timeout: 15_000 })
  const demoResource = (await (await page.request.get(`/api/backend/v1/jobs/${demo.jobId}`)).json()).result
  const quota = await (await page.request.get("/api/backend/v1/quota?mode=guest")).json()
  expect(quota).toMatchObject({ remaining: 0, registrationRequired: true, operations: { analysis: { limit: 1, consumed: 1 } } })
  await page.getByRole("button", { name: ru ? "Создать аккаунт / войти" : "Create account / sign in" }).click()
  const email = `e2e-${locale}-${Date.now()}@example.com`
  await register(page, email, locale)
  const keys: (string | undefined)[] = []
  let failRefresh = false
  await page.route("**/api/backend/v1/guest-claims", async route => {
    keys.push(route.request().headers()["idempotency-key"])
    const response = await route.fetch()
    expect(response.status()).toBe(200)
    if (keys.length === 1) await route.abort("failed") // Receipt persisted, response lost.
    else { failRefresh = true; await route.fulfill({ response }) }
  })
  await page.route("**/api/backend/v1/profile", async route => {
    if (failRefresh && route.request().method() === "GET") {
      failRefresh = false
      await route.fulfill({ status: 503, json: { error: { code: "service_unavailable", message: "Unavailable", details: [] } } })
    } else await route.continue()
  })
  const claim = page.getByRole("button", { name: ru ? "Сохранить демо в аккаунт" : "Save demo to account" })
  await claim.click()
  await expect(page.getByRole("status")).toHaveText(ru ? "Не удалось связаться с сервером. Попробуйте снова." : "Could not reach the server. Try again.")
  await claim.click()
  const reload = page.getByRole("button", { name: ru ? "Обновить данные аккаунта" : "Reload account data" })
  await expect(reload).toBeEnabled()
  await reload.click()
  await expect(page.getByText(ru ? "Демо перенесено в аккаунт." : "Demo saved to your account.")).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBeTruthy()
  expect(keys[1]).toBe(keys[0])
  const claimed = await (await page.request.get("/api/backend/v1/history?limit=100")).json()
  expect(claimed.items).toHaveLength(1)
  expect(claimed.items[0].analysisId).toBe(demoResource.analysisId)
  expect(claimed.items[0].snapshot).toEqual(demoResource.snapshot)
  expect((await (await page.request.get("/api/backend/v1/profile")).json()).profile).toEqual(demoResource.snapshot.profile)
  await page.getByRole("button", { name: copy.newAnalysis, exact: true }).first().click()
  await task(page, "Persisted React task", locale)
  await page.reload()
  await expect(page.getByText("Persisted React task", { exact: true })).toBeVisible({ timeout: 15_000 })
  const result = await page.request.get("/api/backend/v1/history?limit=100")
  const items = (await result.json()).items
  expect(items).toHaveLength(2)
  const analysisId = items.find((entry: { snapshot: { vacancy: { title: string } } }) => entry.snapshot.vacancy.title === "Persisted React task").analysisId
  const otherDevice = await browser.newContext({ viewport: { width: 375, height: 900 } })
  const other = await otherDevice.newPage()
  await login(other, email, locale)
  await other.getByRole("button", { name: copy.profile, exact: true }).first().click()
  await expect(other.getByLabel(copy.specialization, { exact: true })).toHaveValue("Frontend Developer")
  await expect(other.getByLabel(copy.preferredRate, { exact: true })).toHaveValue("65")
  await other.getByRole("button", { name: copy.history, exact: true }).first().click()
  await expect(other.getByRole("button", { name: /Persisted React task/ })).toBeVisible()
  await expect(other.getByRole("button", { name: /Demo React task/ })).toBeVisible()
  await other.getByLabel(`${ru ? "Статус отклика" : "Application status"}: Persisted React task`).selectOption("applied")
  await expect(other.getByLabel(`${ru ? "Статус отклика" : "Application status"}: Persisted React task`)).toHaveValue("applied")
  await other.getByRole("combobox", { name: copy.historyVerdictFilter }).selectOption("NO_GO")
  await expect(other.getByRole("button", { name: /Demo React task/ })).toHaveCount(0)
  await other.getByRole("combobox", { name: ru ? "Фильтр по статусу отклика" : "Filter application status" }).selectOption("applied")
  await expect(other.getByRole("button", { name: /Persisted React task/ })).toBeVisible()
  await other.getByLabel(`${ru ? "Статус отклика" : "Application status"}: Persisted React task`).selectOption("hired")
  await expect(other.getByText(copy.historyNoMatches)).toBeVisible()
  await other.getByRole("button", { name: copy.historyResetFilters }).click()
  await expect(other.getByRole("button", { name: /Demo React task/ })).toBeVisible()
  await expect(other.getByRole("button", { name: /Persisted React task/ })).toBeVisible()
  await expect(other.getByLabel(`${ru ? "Статус отклика" : "Application status"}: Persisted React task`)).toHaveValue("hired")
  expect(await other.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
  await other.screenshot({ path: test.info().outputPath(`history-filters-${locale}.png`), fullPage: true })
  if (!ru) {
  const strangerContext = await browser.newContext()
  const stranger = await strangerContext.newPage()
  await register(stranger, `stranger-${Date.now()}@example.com`)
  expect((await stranger.request.get(`/api/backend/v1/analyses/${analysisId}`)).status()).toBe(404)
  expect((await stranger.request.get("/api/backend/v1/history")).ok()).toBe(true)
  expect((await (await stranger.request.get("/api/backend/v1/history")).json()).items).toEqual([])
  await strangerContext.close()
  }
  await otherDevice.close()
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
