import { beforeEach, describe, expect, it } from "vitest"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import type { Locale } from "@/lib/types"
import { createServerWebsite } from "@/lib/web/server"
import { WebsiteApp } from "./website-app"

function historyServer(initialLocale: Locale) {
  let locale = initialLocale
  let fail = false
  let hold = false
  let holdStatus = false
  let holdJob = false
  let release: (() => void) | undefined
  let releaseJob: (() => void) | undefined
  const records = [
    { id: "g1", verdict: "GO", status: "applied" },
    { id: "g2", verdict: "GO", status: "applied" },
    { id: "g3", verdict: "GO", status: "applied" },
    { id: "g4", verdict: "GO", status: "not_applied" },
    { id: "n1", verdict: "NO_GO", status: "applied" },
    { id: "n2", verdict: "NO_GO", status: "rejected" },
  ]
  const resource = (row: typeof records[number]) => ({ analysisId: row.id, createdAt: "2026-10-22T12:00:00Z",
    analysis: { ...goAnalysis, score: row.verdict === "GO" ? 80 : 40, status: row.verdict },
    applicationStatus: row.status, snapshot: { profileRevision: "1", profile: defaultProfile, vacancy: { ...detectedJob, title: row.id } } })
  let published: ReturnType<typeof resource> | undefined
  const server = createServerWebsite({ fetch: async (url, init) => {
    const { pathname, searchParams } = new URL(String(url), "https://fitcheck.test")
    const path = pathname.replace("/api/backend/", "")
    if (path === "v1/auth/session") return Response.json({ user: { id: "user", email: "test@example.com", emailVerified: true }, csrfToken: "csrf" })
    if (path === "v1/profile") return Response.json({ profile: defaultProfile, revision: "1" })
    if (path === "v1/preferences") {
      if (init?.method === "PUT") locale = JSON.parse(String(init.body)).locale
      return Response.json({ locale })
    }
    if (path === "v1/draft") return Response.json(null)
    if (path === "v1/analysis-jobs" && init?.method === "POST") {
      const row = { id: "new", verdict: "GO", status: "not_applied" }
      records.unshift(row)
      published = resource(row)
      published.snapshot.vacancy = JSON.parse(String(init.body)).vacancy
      return Response.json({ jobId: "new-job" }, { status: 202 })
    }
    if (path === "v1/jobs/new-job") {
      if (holdJob) { holdJob = false; await new Promise<void>(resolve => { releaseJob = resolve }) }
      return Response.json({ jobId: "new-job", type: "analysis", status: "succeeded", analysisId: "new", result: published })
    }
    if (path === "v1/history") {
      if (fail) { fail = false; return Response.json({ error: { code: "service_unavailable", message: "Unavailable", details: [] } }, { status: 503 }) }
      const verdict = searchParams.get("verdict") ?? ""
      const status = searchParams.get("applicationStatus") ?? ""
      const cursor = searchParams.get("cursor")
      const offset = cursor ? Number(cursor.split(":")[1]) : 0
      if (cursor && cursor !== `next:${offset}:${verdict}:${status}`) throw new Error("Cursor reused with different filters")
      const filtered = records.filter(row => (!verdict || row.verdict === verdict) && (!status || row.status === status))
      const page = { items: filtered.slice(offset, offset + 2).map(resource), hasMore: filtered.length > offset + 2, nextCursor: filtered.length > offset + 2 ? `next:${offset + 2}:${verdict}:${status}` : null }
      // Capture the old response before a later refresh/selection completes.
      if (hold) { hold = false; await new Promise<void>(resolve => { release = resolve }) }
      return Response.json(page)
    }
    const statusPath = /^v1\/analyses\/(\w+)\/application-status$/.exec(path)
    if (statusPath && init?.method === "PUT") {
      if (holdStatus) { holdStatus = false; await new Promise<void>(resolve => { release = resolve }) }
      records.find(row => row.id === statusPath[1])!.status = JSON.parse(String(init.body)).applicationStatus
      return Response.json({})
    }
    throw new Error(`Unexpected request: ${path}`)
  } })
  return { server, addNewest: () => { records.unshift({ id: "fresh", verdict: "GO", status: "not_applied" }) }, failNext: () => { fail = true }, holdNext: () => { hold = true }, holdNextStatus: () => { holdStatus = true }, holdNextJob: () => { holdJob = true }, releaseJob: () => { if (!releaseJob) throw new Error("No held job"); releaseJob() }, release: () => { const finish = release ?? releaseJob; if (!finish) throw new Error("No held response"); finish() } }
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })

const copies = [
  { locale: "en" as const, history: "History", verdict: "Filter by verdict", status: "Filter application status", rowStatus: "Application status", more: "Load more", reset: "Reset filters", empty: "No analyses match these filters." },
  { locale: "ru" as const, history: "История", verdict: "Фильтр по вердикту", status: "Фильтр по статусу отклика", rowStatus: "Статус отклика", more: "Загрузить ещё", reset: "Сбросить фильтры", empty: "Нет анализов с такими фильтрами." },
]

describe("history filters", () => {
  it("preserves loaded records while pagination overlaps a refreshed first page with a new insert", async () => {
    const user = userEvent.setup(); const h = historyServer("en")
    render(<WebsiteApp server={h.server} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    h.holdNext()
    await user.click(screen.getByRole("button", { name: "Load more" }))
    h.addNewest()
    await user.click(screen.getByRole("button", { name: "RU" }))
    expect(await screen.findByRole("combobox", { name: "Фильтр по вердикту" })).toBeDisabled()
    await act(async () => { h.release() })
    expect(screen.getByRole("button", { name: /^g2,/ })).toBeVisible()
    expect(screen.getAllByRole("button", { name: /^g\d,/ })).toHaveLength(4)
  })
  it.each(["filter", "status"] as const)("preserves a pending %s operation when an analysis finishes in the background", async operation => {
    const user = userEvent.setup(); const h = historyServer("en")
    h.holdNextJob()
    render(<WebsiteApp server={h.server} />)
    await user.click(await screen.findByRole("button", { name: "Paste text" }))
    await user.type(screen.getByLabelText("Task title"), "new")
    await user.type(screen.getByLabelText("Task description"), "Build a production React application for customers.")
    await user.click(screen.getByRole("button", { name: "Review task" }))
    await user.click(screen.getByRole("button", { name: "Analyze task" }))
    await user.click(screen.getAllByRole("button", { name: "History" })[0])
    if (operation === "filter") {
      h.holdNext()
      await user.selectOptions(screen.getByRole("combobox", { name: "Filter by verdict" }), "NO_GO")
    } else {
      h.holdNextStatus()
      await user.selectOptions(screen.getByRole("combobox", { name: "Application status: g1" }), "hired")
    }
    await act(async () => { h.releaseJob() })
    await act(async () => { h.release() })
    if (operation === "filter") {
      expect(screen.getByRole("combobox", { name: "Filter by verdict" })).toHaveValue("NO_GO")
      expect(screen.queryByRole("button", { name: /^new,/ })).not.toBeInTheDocument()
    } else expect(screen.getByRole("combobox", { name: "Application status: g1" })).toHaveValue("hired")
  })
  it("uses the current filters when an analysis completes after navigation to history", async () => {
    const user = userEvent.setup(); const h = historyServer("en")
    h.holdNextJob()
    render(<WebsiteApp server={h.server} />)
    await user.click(await screen.findByRole("button", { name: "Paste text" }))
    await user.type(screen.getByLabelText("Task title"), "new")
    await user.type(screen.getByLabelText("Task description"), "Build a production React application for customers.")
    await user.click(screen.getByRole("button", { name: "Review task" }))
    await user.click(screen.getByRole("button", { name: "Analyze task" }))
    await user.click(screen.getAllByRole("button", { name: "History" })[0])
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by verdict" }), "NO_GO")
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Filter by verdict" })).toBeEnabled())
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter application status" }), "applied")
    expect(await screen.findByRole("button", { name: /^n1,/ })).toBeVisible()
    await act(async () => { h.release() })
    expect(screen.getByRole("combobox", { name: "Filter by verdict" })).toHaveValue("NO_GO")
    expect(screen.getByRole("combobox", { name: "Filter application status" })).toHaveValue("applied")
    expect(screen.queryByRole("button", { name: /^new,/ })).not.toBeInTheDocument()
  })
  it("keeps a newly completed analysis out of nonmatching retained filters until reset", async () => {
    const user = userEvent.setup()
    render(<WebsiteApp server={historyServer("en").server} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by verdict" }), "NO_GO")
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Filter by verdict" })).toBeEnabled())
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter application status" }), "applied")
    expect(await screen.findByRole("button", { name: /^n1,/ })).toBeVisible()
    await user.click(screen.getAllByRole("button", { name: "New analysis" })[0])
    await user.click(screen.getByRole("button", { name: "Paste text" }))
    await user.type(screen.getByLabelText("Task title"), "new")
    await user.type(screen.getByLabelText("Task description"), "Build a production React application for customers.")
    await user.click(screen.getByRole("button", { name: "Review task" }))
    await user.click(screen.getByRole("button", { name: "Analyze task" }))
    expect(await screen.findByLabelText("Fit score 80 out of 100")).toBeVisible()
    await user.click(screen.getAllByRole("button", { name: "History" })[0])
    expect(screen.getByRole("combobox", { name: "Filter by verdict" })).toHaveValue("NO_GO")
    expect(screen.getByRole("combobox", { name: "Filter application status" })).toHaveValue("applied")
    expect(screen.queryByRole("button", { name: /^new,/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Reset filters" }))
    expect(await screen.findByRole("button", { name: /^new,/ })).toBeVisible()
  })
  it.each(copies)("combines filters through pagination/status changes and restores all records on reset in $locale", async copy => {
    const user = userEvent.setup()
    render(<WebsiteApp server={historyServer(copy.locale).server} />)
    await user.click((await screen.findAllByRole("button", { name: copy.history }))[0])
    await user.selectOptions(screen.getByRole("combobox", { name: copy.verdict }), "GO")
    await waitFor(() => expect(screen.getByRole("combobox", { name: copy.verdict })).toBeEnabled())
    await user.selectOptions(screen.getByRole("combobox", { name: copy.status }), "applied")
    await waitFor(() => expect(screen.getByRole("combobox", { name: copy.status })).toBeEnabled())
    await user.click(screen.getByRole("button", { name: copy.more }))
    expect(await screen.findByRole("button", { name: /^g3,/ })).toBeVisible()
    expect(screen.queryByRole("button", { name: /^n1,/ })).not.toBeInTheDocument()
    await user.selectOptions(screen.getByRole("combobox", { name: `${copy.rowStatus}: g1` }), "rejected")
    await waitFor(() => expect(screen.queryByRole("button", { name: /^g1,/ })).not.toBeInTheDocument())
    expect(screen.getByRole("button", { name: /^g2,/ })).toBeVisible()
    await user.selectOptions(screen.getByRole("combobox", { name: copy.status }), "interview")
    expect(await screen.findByText(copy.empty)).toBeVisible()
    await user.click(screen.getByRole("button", { name: copy.reset }))
    expect(await screen.findByRole("button", { name: /^g1,/ })).toBeVisible()
    expect(screen.getByRole("combobox", { name: `${copy.rowStatus}: g1` })).toHaveValue("rejected")
    await user.click(screen.getByRole("button", { name: copy.more }))
    expect(await screen.findByRole("button", { name: /^g4,/ })).toBeVisible()
    await user.click(screen.getByRole("button", { name: copy.more }))
    expect(await screen.findByRole("button", { name: /^n2,/ })).toBeVisible()
    expect(screen.getAllByRole("button", { name: /^[gn]\d,/ })).toHaveLength(6)
    expect(screen.queryByRole("button", { name: copy.more })).not.toBeInTheDocument()
  })

  it("retains both selected filters and matching records after a locale refresh", async () => {
    const user = userEvent.setup()
    render(<WebsiteApp server={historyServer("en").server} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by verdict" }), "NO_GO")
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Filter by verdict" })).toBeEnabled())
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter application status" }), "rejected")
    expect(await screen.findByRole("button", { name: /^n2,/ })).toBeVisible()
    await user.click(screen.getByRole("button", { name: "RU" }))
    expect(await screen.findByRole("combobox", { name: "Фильтр по вердикту" })).toHaveValue("NO_GO")
    expect(screen.getByRole("combobox", { name: "Фильтр по статусу отклика" })).toHaveValue("rejected")
    expect(screen.getAllByRole("button", { name: /^[gn]\d,/ })).toHaveLength(1)
  })

  it("keeps the prior filter and data after a failed request and allows retry", async () => {
    const user = userEvent.setup(); const h = historyServer("en")
    render(<WebsiteApp server={h.server} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    h.failNext()
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by verdict" }), "NO_GO")
    expect(await screen.findByRole("alert")).toBeVisible()
    expect(screen.getByRole("combobox", { name: "Filter by verdict" })).toHaveValue("")
    expect(screen.getByRole("button", { name: /^g1,/ })).toBeVisible()
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by verdict" }), "NO_GO")
    expect(await screen.findByRole("button", { name: /^n1,/ })).toBeVisible()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("keeps an in-flight filter selection when locale data is refreshed", async () => {
    const user = userEvent.setup(); const h = historyServer("en")
    render(<WebsiteApp server={h.server} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    h.holdNext()
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by verdict" }), "NO_GO")
    await user.click(screen.getByRole("button", { name: "RU" }))
    expect(await screen.findByRole("combobox", { name: "Фильтр по вердикту" })).toBeDisabled()
    await act(async () => { h.release() })
    expect(screen.getByRole("combobox", { name: "Фильтр по вердикту" })).toHaveValue("NO_GO")
    expect(screen.getByRole("button", { name: /^n1,/ })).toBeVisible()
    expect(screen.queryByRole("button", { name: /^g1,/ })).not.toBeInTheDocument()
  })

  it("shows a status saved after a simultaneous locale refresh", async () => {
    const user = userEvent.setup(); const h = historyServer("en")
    render(<WebsiteApp server={h.server} />)
    await user.click((await screen.findAllByRole("button", { name: "History" }))[0])
    h.holdNextStatus()
    await user.selectOptions(screen.getByRole("combobox", { name: "Application status: g1" }), "hired")
    await user.click(screen.getByRole("button", { name: "RU" }))
    expect(await screen.findByRole("combobox", { name: "Статус отклика: g1" })).toBeDisabled()
    await act(async () => { h.release() })
    expect(screen.getByRole("combobox", { name: "Статус отклика: g1" })).toHaveValue("hired")
    expect(screen.getByRole("combobox", { name: "Статус отклика: g1" })).toBeEnabled()
  })
})
