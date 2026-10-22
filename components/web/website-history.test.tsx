import { beforeEach, describe, expect, it } from "vitest"
import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import type { Locale } from "@/lib/types"
import { createServerWebsite } from "@/lib/web/server"
import { WebsiteApp } from "./website-app"

// Only the HTTP boundary is replaced; the app, adapter, validation and polling are real.
function historyServer(locale: Locale, { changed = false, fail = false, waitForJob }: { changed?: boolean; fail?: boolean; waitForJob?: Promise<void> } = {}) {
  let revision = changed ? "2" : "1"
  let profile = structuredClone(defaultProfile)
  let admittedRevision = revision
  let admittedProfile = structuredClone(profile)
  const original = {
    analysisId: "original", createdAt: "2026-10-20T10:00:00Z",
    analysis: { ...goAnalysis, score: 86 }, applicationStatus: "not_applied",
    snapshot: { profileRevision: "1", profile: structuredClone(defaultProfile), vacancy: detectedJob },
  }
  const records = [original]
  const resource = (record: typeof original) => ({ ...record, currentProfileRevision: revision, profileChanged: record.snapshot.profileRevision !== revision })
  const fetcher: typeof fetch = async (url, init) => {
    const path = String(url).replace("/api/backend/", "")
    if (path === "v1/auth/session") return Response.json({ user: { id: "account", email: "test@example.com", emailVerified: true }, csrfToken: "csrf-test" })
    if (path === "v1/profile") {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body))
        if (body.expectedRevision !== revision) throw new Error("Wrong profile revision")
        profile = body.profile
        revision = String(Number(revision) + 1)
      }
      return Response.json({ profile, revision })
    }
    if (path === "v1/preferences") return Response.json({ locale })
    if (path === "v1/draft") return Response.json(null)
    if (path === "v1/history?limit=100") return Response.json({ items: records.map(resource), hasMore: false, nextCursor: null })
    if (path === "v1/analyses/original/reanalyses" && init?.method === "POST") {
      admittedRevision = revision
      admittedProfile = structuredClone(profile)
      return Response.json({ jobId: "reanalysis" }, { status: 202 })
    }
    if (path === "v1/jobs/reanalysis") {
      await waitForJob
      if (fail) return Response.json({ jobId: "reanalysis", type: "analysis", status: "failed", error: { code: "invalid_output" } })
      const result = { ...original, analysisId: "recalculated", createdAt: "2026-10-21T10:00:00Z", analysis: { ...goAnalysis, score: 62, status: "NO_GO" as const }, snapshot: { ...original.snapshot, profileRevision: admittedRevision, profile: admittedProfile } }
      records.unshift(result)
      return Response.json({ jobId: "reanalysis", type: "analysis", status: "succeeded", analysisId: "recalculated", result: resource(result) })
    }
    throw new Error(`Unexpected request: ${path}`)
  }
  return createServerWebsite({ fetch: fetcher, delay: async () => {}, maxPolls: 2 })
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })

describe("history profile revisions", () => {
  it.each([
    { locale: "en" as const, history: "History", profile: "Profile", rate: "Preferred hourly rate", save: "Save changes", changed: "Profile changed", action: "Reanalyze with current profile", result: "Fit score 62 out of 100", old: "Profile version: v1", current: "Profile version: v2" },
    { locale: "ru" as const, history: "История", profile: "Профиль", rate: "Желаемая ставка в час", save: "Сохранить изменения", changed: "Профиль изменён", action: "Пересчитать по текущему профилю", result: "Оценка соответствия 62 из 100", old: "Версия профиля: v1", current: "Версия профиля: v2" },
  ])("marks a saved analysis after a profile edit and retains both results after reanalysis in $locale", async copy => {
    const user = userEvent.setup()
    render(<WebsiteApp server={historyServer(copy.locale)} />)
    await user.click((await screen.findAllByRole("button", { name: copy.history }))[0])
    expect(screen.getByText(copy.old)).toBeVisible()
    expect(screen.queryByText(copy.changed)).not.toBeInTheDocument()

    await user.click(screen.getAllByRole("button", { name: copy.profile })[0])
    await user.clear(screen.getByLabelText(copy.rate, { exact: true }))
    await user.type(screen.getByLabelText(copy.rate, { exact: true }), "70")
    await user.click(screen.getByRole("button", { name: copy.save }))
    await user.click((await screen.findAllByRole("button", { name: copy.history }))[0])
    expect(await screen.findByText(copy.changed)).toBeVisible()
    await user.click(screen.getByRole("button", { name: copy.action }))
    expect(await screen.findByLabelText(copy.result)).toBeVisible()

    await user.click(screen.getAllByRole("button", { name: copy.history })[0])
    expect(screen.getByText(copy.old)).toBeVisible()
    expect(screen.getByText(copy.current)).toBeVisible()
    expect(screen.getAllByText(copy.changed)).toHaveLength(1)
    const analyses = screen.getAllByRole("button", { name: /Senior Python Backend Developer/ })
    expect(analyses).toHaveLength(2)
    expect(within(analyses[0]).getByText("62")).toBeVisible()
    expect(within(analyses[1]).getByText("86")).toBeVisible()
  })

  it("returns to history after a failed reanalysis and preserves the original result", async () => {
    const user = userEvent.setup()
    render(<WebsiteApp server={historyServer("en", { changed: true, fail: true })} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    await user.click(screen.getByRole("button", { name: "Reanalyze with current profile" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("The service returned an invalid result. Try again.")
    expect(screen.getByRole("heading", { name: "Analysis history" })).toBeVisible()
    expect(screen.getByRole("button", { name: /Senior Python Backend Developer, 86/ })).toBeVisible()
    expect(screen.getByRole("button", { name: "Reanalyze with current profile" })).toBeEnabled()
  })

  it.each([true, false])("keeps profile edits visible when a background reanalysis settles after navigation (failure: %s)", async fail => {
    const user = userEvent.setup()
    let finish!: () => void
    const pending = new Promise<void>(resolve => { finish = resolve })
    const server = historyServer("en", { changed: true, fail, waitForJob: pending })
    render(<WebsiteApp server={server} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    await user.click(screen.getByRole("button", { name: "Reanalyze with current profile" }))
    await user.click(screen.getAllByRole("button", { name: "Profile" })[0])
    await user.clear(screen.getByLabelText("Specialization"))
    await user.type(screen.getByLabelText("Specialization"), "Unsaved profile edit")
    await act(async () => { finish() })
    if (fail) expect(await screen.findByRole("alert")).toHaveTextContent("The service returned an invalid result.")
    expect(screen.getByLabelText("Specialization")).toHaveValue("Unsaved profile edit")
    if (!fail) {
      await user.click(screen.getAllByRole("button", { name: "History" })[0])
      expect(screen.getByRole("button", { name: /Senior Python Backend Developer, 62/ })).toBeVisible()
    }
  })

  it.each([true, false])("returns to task selection after saving a profile while reanalysis is pending (failure: %s)", async fail => {
    const user = userEvent.setup()
    let finish!: () => void
    const pending = new Promise<void>(resolve => { finish = resolve })
    render(<WebsiteApp server={historyServer("en", { changed: true, fail, waitForJob: pending })} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    await user.click(screen.getByRole("button", { name: "Reanalyze with current profile" }))
    await user.click(screen.getAllByRole("button", { name: "Profile" })[0])
    await user.clear(screen.getByLabelText("Specialization"))
    await user.type(screen.getByLabelText("Specialization"), "Updated profile")
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    expect(await screen.findByRole("heading", { name: "Choose how to add a task" })).toBeVisible()
    await act(async () => { finish() })
    expect(screen.getByRole("heading", { name: "Choose how to add a task" })).toBeVisible()
    expect(screen.queryByRole("status")).not.toBeInTheDocument()
  })
})
