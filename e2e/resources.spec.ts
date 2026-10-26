import { expect, test } from "@playwright/test"

test("main pages load without missing resources and unknown routes still return 404", async ({ page }) => {
  const missing: string[] = []
  page.on("response", response => {
    if (response.status() === 404) missing.push(response.url())
  })
  for (const path of ["/", "/auth/password-reset", "/auth/verify-email"]) {
    const response = await page.goto(path)
    expect(response?.status()).toBe(200)
    await page.waitForLoadState("networkidle")
    expect(missing, `Missing resources on ${path}`).toEqual([])
  }
  expect((await page.request.get("/missing-resource-any584.js")).status()).toBe(404)
})
