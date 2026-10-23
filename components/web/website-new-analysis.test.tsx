import { beforeEach, expect, it } from "vitest"
import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { createServerWebsite } from "@/lib/web/server"
import { WebsiteApp } from "./website-app"
import { createMemoryWebsiteRepository } from "@/lib/web/memory-repository"

function setupServer({ text = false, extraction, analysis }: { text?: boolean; extraction?: Promise<void>; analysis?: Promise<void> } = {}) {
  let draft: { vacancy: typeof detectedJob; locale: string } | null = {
    vacancy: { ...detectedJob, ...(text ? { url: undefined } : { url: "https://jobs.example/old" }) }, locale: "en",
  }
  const original = {
    analysisId: "original", createdAt: "2026-10-20T10:00:00Z", analysis: goAnalysis,
    applicationStatus: "not_applied", currentProfileRevision: "1", profileChanged: false,
    snapshot: { profileRevision: "1", profile: defaultProfile, vacancy: detectedJob },
  }
  let jobNumber = 0
  const jobs = new Map<string, typeof detectedJob>()
  const fetcher: typeof fetch = async (url, init) => {
    const path = String(url).replace("/api/backend/", "")
    if (path === "v1/auth/session") return Response.json({ user: { id: "account", email: "test@example.com", emailVerified: true }, csrfToken: "csrf-test" })
    if (path === "v1/profile") return Response.json({ profile: defaultProfile, revision: "1" })
    if (path === "v1/preferences") return Response.json({ locale: "en" })
    if (path === "v1/draft") {
      if (init?.method === "PUT") draft = JSON.parse(String(init.body))
      return Response.json(draft)
    }
    if (path === "v1/history?limit=100") return Response.json({ items: [original], hasMore: false, nextCursor: null })
    if (path === "v1/extractions") { await extraction; return Response.json({ vacancy: detectedJob }) }
    if (path === "v1/analysis-jobs") {
      const jobId = `job-${++jobNumber}`
      jobs.set(jobId, JSON.parse(String(init?.body)).vacancy)
      return Response.json({ jobId }, { status: 202 })
    }
    if (path.startsWith("v1/jobs/")) {
      const jobId = path.split("/").at(-1)!
      if (jobId !== "job-2") await analysis
      const result = { ...original, snapshot: { ...original.snapshot, vacancy: jobs.get(jobId) ?? detectedJob } }
      return Response.json({ jobId, type: "analysis", status: "succeeded", analysisId: "original", result })
    }
    throw new Error(`Unexpected request: ${path}`)
  }
  return createServerWebsite({ fetch: fetcher })
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })

async function expectEmptySource(user: ReturnType<typeof userEvent.setup>) {
  expect(await screen.findByLabelText("Task URL")).toHaveValue("")
  await user.click(screen.getByRole("button", { name: "Paste text" }))
  expect(screen.getByLabelText("Task title")).toHaveValue("")
  expect(screen.getByLabelText("Task description")).toHaveValue("")
  expect(screen.getByLabelText("Required skills")).toHaveValue("")
}

it.each([false, true])("clears a stored task and preserves profile and history (text: %s)", async text => {
  const user = userEvent.setup()
  const server = setupServer({ text })
  render(<WebsiteApp server={server} />)
  await screen.findByRole("heading", { name: "Choose how to add a task" })
  await user.click(screen.getAllByRole("button", { name: "New analysis" })[0])
  await expectEmptySource(user)
  const snapshot = await server.repository.loadSnapshot()
  expect(snapshot.draft).toBeNull()
  expect(snapshot.profile).toEqual(defaultProfile)
  expect(snapshot.history).toHaveLength(1)

  await user.click(screen.getAllByRole("button", { name: "History" })[0])
  await user.click(screen.getByRole("button", { name: /Senior Python Backend Developer, 82/ }))
  expect(await screen.findByLabelText("Fit score 82 out of 100")).toBeVisible()
  await user.click(screen.getAllByRole("button", { name: "New analysis" })[0])
  await expectEmptySource(user)
  await user.click(screen.getAllByRole("button", { name: "History" })[0])
  expect(screen.getByRole("button", { name: /Senior Python Backend Developer, 82/ })).toBeVisible()
})

it("clears unsaved input even when task selection is already mounted", async () => {
  const user = userEvent.setup()
  render(<WebsiteApp server={setupServer()} />)
  await user.clear(await screen.findByLabelText("Task URL"))
  await user.type(screen.getByLabelText("Task URL"), "https://jobs.example/unsaved")
  await user.click(screen.getByRole("button", { name: "Paste text" }))
  await user.type(screen.getByLabelText("Task title"), "Unsaved task")
  await user.type(screen.getByLabelText("Task description"), "Unsaved task requirements")
  await user.click(screen.getAllByRole("button", { name: "New analysis" })[0])
  await expectEmptySource(user)
})

it("does not restore a previous task when its extraction finishes after reset", async () => {
  const user = userEvent.setup()
  let finish!: () => void
  const extraction = new Promise<void>(resolve => { finish = resolve })
  const server = setupServer({ extraction })
  render(<WebsiteApp server={server} />)
  await user.click(await screen.findByRole("button", { name: "Load task" }))
  await user.click(screen.getAllByRole("button", { name: "New analysis" })[0])
  await expectEmptySource(user)
  await act(async () => { finish() })
  expect(screen.queryByRole("heading", { name: "Review the task" })).not.toBeInTheDocument()
  expect(screen.getByLabelText("Task title")).toHaveValue("")
  expect((await server.repository.loadSnapshot()).draft).toBeNull()
})

it("keeps the new form empty when a previous analysis completes", async () => {
  const user = userEvent.setup()
  const repository = createMemoryWebsiteRepository()
  const account = await repository.createUser({ name: "Nikita", email: "test@example.com", password: "password-123" })
  await repository.saveProfile(account.id, defaultProfile)
  await repository.saveDraft(account.id, { ...detectedJob, sourceMode: "text", updatedAt: new Date().toISOString() })
  let finish!: () => void
  const analysis = new Promise<void>(resolve => { finish = resolve })
  render(<WebsiteApp repository={repository} api={{
    extractVacancy: async () => { throw new Error("Unexpected extraction") },
    suggestSkills: async () => { throw new Error("Unexpected suggestions") },
    analyzeVacancy: async () => { await analysis; return goAnalysis },
  }} />)
  await user.click(await screen.findByRole("button", { name: "Review task" }))
  await user.click(screen.getByRole("button", { name: "Analyze task" }))
  await user.click(screen.getAllByRole("button", { name: "New analysis" })[0])
  await expectEmptySource(user)
  await act(async () => { finish() })
  expect(screen.getByLabelText("Task title")).toHaveValue("")
  expect(screen.queryByLabelText("Fit score 82 out of 100")).not.toBeInTheDocument()
  expect((await repository.loadSnapshot()).history).toHaveLength(1)
})

it("does not reopen an automatically resumed result after starting a new task", async () => {
  const user = userEvent.setup()
  let finish!: () => void
  const analysis = new Promise<void>(resolve => { finish = resolve })
  localStorage.setItem("fitcheck.pending-analysis.account", JSON.stringify({ jobId: "previous-job" }))
  const server = setupServer({ analysis })
  render(<WebsiteApp server={server} />)
  await user.click((await screen.findAllByRole("button", { name: "New analysis" }))[0])
  await expectEmptySource(user)
  expect(server.hasPendingAnalysis()).toBe(false)
  await act(async () => { finish() })
  expect(screen.getByLabelText("Task title")).toHaveValue("")
  expect(screen.queryByLabelText("Fit score 82 out of 100")).not.toBeInTheDocument()
})

it("submits the new task independently while the old server analysis is pending", async () => {
  const user = userEvent.setup()
  let finish!: () => void
  const analysis = new Promise<void>(resolve => { finish = resolve })
  render(<WebsiteApp server={setupServer({ text: true, analysis })} />)
  await user.click(await screen.findByRole("button", { name: "Review task" }))
  await user.click(screen.getByRole("button", { name: "Analyze task" }))
  await user.click(screen.getAllByRole("button", { name: "New analysis" })[0])
  await expectEmptySource(user)
  await user.type(screen.getByLabelText("Task title"), "New independent task")
  await user.type(screen.getByLabelText("Task description"), "Build a different application with accessible forms.")
  await user.click(screen.getByRole("button", { name: "Review task" }))
  expect(screen.getByLabelText("Fixed budget")).toHaveValue(null)
  await user.click(screen.getByRole("button", { name: "Analyze task" }))
  expect(await screen.findByText("New independent task", { exact: true })).toBeVisible()
  await act(async () => { finish() })
  expect(screen.getByText("New independent task", { exact: true })).toBeVisible()
})
