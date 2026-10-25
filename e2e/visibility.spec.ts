import { chromium, expect, test, type Page } from '@playwright/test'
import { webMessages } from '../lib/i18n/web-messages'
import type { ClientEvent } from '../lib/metrics/types'

import { spawn } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// Attach to a fresh, disposable browser without Playwright's forced focus.
// noDefaults applies only to the default persistent context, not newContext().
async function realTabs() {
  const directory = await mkdtemp(join(tmpdir(), 'fitcheck-visibility-'))
  const process = spawn(chromium.executablePath(), [
    `--user-data-dir=${directory}`, '--remote-debugging-port=0',
    '--no-first-run', '--no-default-browser-check', '--lang=en-US', 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'] })
  const close = async () => {
    if (process.pid && process.exitCode === null && process.signalCode === null) {
      const exited = new Promise<void>(resolve => process.once('exit', () => resolve()))
      process.kill()
      await exited
    }
    await rm(directory, { recursive: true, force: true })
  }
  try {
    const endpoint = await new Promise<string>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Chromium CDP startup timed out')), 15_000)
      process.once('error', error => { clearTimeout(timeout); reject(error) })
      process.stderr.on('data', data => {
        const match = String(data).match(/DevTools listening on (ws:\/\/[^\s]+)/)
        if (match) { clearTimeout(timeout); resolve(match[1]) }
      })
    })
    const browser = await chromium.connectOverCDP(endpoint, { noDefaults: true })
    return { context: browser.contexts()[0], close }
  } catch (error) { await close(); throw error }
}

const copy = webMessages.en
async function register(page: Page) {
  const email = `visibility-${Date.now()}@example.com`
  await page.getByLabel(copy.email, { exact: true }).fill(email)
  await page.getByLabel(copy.password, { exact: true }).fill('correct horse battery staple')
  await page.getByRole('button', { name: copy.createAccount, exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Verify your email' })).toBeVisible()
  const mail = await page.request.get(`http://127.0.0.1:38154/testing/mail?email=${encodeURIComponent(email)}`)
  await page.getByLabel('Verification code').fill((await mail.json()).token)
  await page.getByRole('button', { name: 'Verify', exact: true }).click()
}
async function profile(page: Page) {
  await page.getByLabel(copy.specialization, { exact: true }).fill('Frontend Developer')
  await page.getByPlaceholder(copy.skillsPlaceholder).fill('React')
  await page.getByPlaceholder(copy.skillsPlaceholder).press('Enter')
  await page.getByLabel(copy.preferredRate, { exact: true }).fill('65')
  await page.getByRole('checkbox', { name: copy.workRemote, exact: true }).check()
  await page.getByRole('button', { name: copy.saveProfile, exact: true }).click()
}
for (const flow of ['demo', 'account'] as const) test(`${flow}: background completion waits for a real tab switch`, async ({}, testInfo) => {
  test.skip(!testInfo.config.metadata.realVisibility || Boolean(testInfo.project.use.headless ?? true), 'Requires playwright.visibility.config.ts --headed')
  const { context, close } = await realTabs()
  try {
    const page = await context.newPage()
    const events: ClientEvent[] = []
    await page.route('**/api/metrics', async route => {
      events.push(...route.request().postDataJSON().events)
      await route.fulfill({ status: 200, json: { delivered: true } })
    })
    const views = () => events.filter(event => event.name === 'analysis_result_viewed')
    await page.goto('http://127.0.0.1:38153/')
    await page.bringToFront()
    await page.getByRole('button', { name: 'EN', exact: true }).click()
    if (flow === 'demo') await page.getByRole('button', { name: copy.tryDemo }).click()
    else await register(page)
    await profile(page)
    await page.getByRole('button', { name: copy.pasteText, exact: true }).click()
    const title = `Background ${flow} result`
    await page.getByLabel(copy.vacancyTitle, { exact: true }).fill(title)
    await page.getByLabel(copy.vacancyDescription, { exact: true }).fill('Build a React application with TypeScript and accessible forms for customers.')
    await page.getByRole('button', { name: copy.reviewVacancy, exact: true }).click()
    // Hold job admission so switching tabs always precedes completion/polling.
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    let admitted!: () => void
    const admission = new Promise<void>(resolve => { admitted = resolve })
    await page.route('**/api/backend/v1/analysis-jobs', async route => {
      const response = await route.fetch()
      admitted()
      await gate
      await route.fulfill({ response })
    })
    await page.getByRole('button', { name: copy.analyzeVacancy, exact: true }).click()
    await admission
    const other = await context.newPage()
    await other.goto('about:blank')
    await other.bringToFront()
    await expect.poll(() => page.evaluate(() => document.visibilityState)).toBe('hidden')
    release()
    // DOM completion is observable while the real document stays hidden.
    await expect(page.getByText(title, { exact: true })).toHaveCount(1, { timeout: 15_000 })
    expect(await page.evaluate(() => document.visibilityState)).toBe('hidden')
    expect(views()).toHaveLength(0)
    const returnedAt = Date.now()
    await page.bringToFront()
    await expect.poll(() => views().length).toBe(1)
    expect(views()[0].properties).toMatchObject({ flow })
    expect(Date.parse(views()[0].occurredAt)).toBeGreaterThanOrEqual(returnedAt)
    const firstId = views()[0].eventId
    await other.bringToFront()
    await expect.poll(() => page.evaluate(() => document.visibilityState)).toBe('hidden')
    await page.bringToFront()
    await expect.poll(() => page.evaluate(() => document.visibilityState)).toBe('visible')
    expect(views().map(event => event.eventId)).toEqual([firstId])
    await testInfo.attach(`${flow}-observations`, { body: JSON.stringify({ flow, returnedAt, views: views() }, null, 2), contentType: 'application/json' })
    await other.close()
  } finally { await close() }
})
