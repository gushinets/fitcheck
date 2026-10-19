import { beforeEach, describe, expect, it, vi } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { BackendApiError } from "@/lib/backend/client"
import { createServerWebsite } from "./server"

const resource = {
  analysisId: "analysis-1", createdAt: "2026-10-19T10:00:00Z", analysis: goAnalysis,
  snapshot: { profileRevision: "2", profile: defaultProfile, vacancy: detectedJob }, applicationStatus: "not_applied",
}
const input = { profile: defaultProfile, job: detectedJob, locale: "en" as const, memory: [] }
const error = (status: number, code: string) => Response.json({ error: { code, message: code, details: [] } }, { status })

function harness() {
  let account = "a"
  let verified = true
  const calls: { path: string; method: string; headers: Headers; body: unknown }[] = []
  const overrides = new Map<string, () => Response | Promise<Response>>()
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const path = String(url).replace("/api/backend/", "")
    calls.push({ path, method: init?.method ?? "GET", headers: new Headers(init?.headers), body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (overrides.has(path)) return overrides.get(path)!()
    if (path === "v1/auth/session" || path === "v1/auth/login" || path === "v1/auth/register") return Response.json({ user: { id: account, email: `${account}@example.com`, emailVerified: verified }, csrfToken: `csrf-${account}` })
    if (path === "v1/auth/csrf") return Response.json({ csrfToken: "bootstrap" })
    if (path === "v1/profile") return Response.json({ profile: defaultProfile, revision: "2" })
    if (path === "v1/preferences") return Response.json({ locale: "ru" })
    if (path === "v1/draft") return Response.json(null)
    if (path.startsWith("v1/history")) return Response.json({ items: account === "a" ? [resource] : [], hasMore: false, nextCursor: null })
    if (path === "v1/analysis-jobs") return Response.json({ jobId: "job-1" }, { status: 202 })
    if (path === "v1/jobs/job-1") return Response.json({ jobId: "job-1", type: "analysis", status: "succeeded", analysisId: "analysis-1", result: resource })
    if (path === "v1/auth/logout") return new Response(null, { status: 204 })
    if (path === "v1/guest-sessions") return Response.json({ csrfToken: "guest-proof" })
    if (path === "v1/guest-claims") return Response.json({ claimedCount: 1, profileImported: false })
    throw new Error(`Unexpected request: ${path}`)
  })
  const server = () => createServerWebsite({ fetch: fetcher, delay: async () => {}, maxPolls: 2 })
  return { server, calls, overrides, setAccount: (id: string) => { account = id }, setVerified: (value: boolean) => { verified = value } }
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })

describe("server website", () => {
  it("authenticates with bootstrap CSRF and submits only credentials, never a client owner", async () => {
    const h = harness(); const server = h.server()
    await server.repository.createUser({ name: "Ignored local display name", email: "a@example.com", password: "long-password-123" })
    const registration = h.calls.find(c => c.path === "v1/auth/register")!
    expect(registration.headers.get("x-csrf-token")).toBe("bootstrap")
    expect(registration.body).toEqual({ email: "a@example.com", password: "long-password-123" })
  })

  it("restores server profile/history on a second browser and isolates the next account after logout", async () => {
    const h = harness(); const first = h.server(); const second = h.server()
    expect((await first.repository.loadSnapshot()).history[0].id).toBe("analysis-1")
    expect((await second.repository.loadSnapshot()).history[0].profileRevision).toBe("2")
    await first.repository.signOut(); h.setAccount("b")
    const loaded = await first.repository.loadSnapshot()
    expect(loaded.user?.id).toBe("b"); expect(loaded.history).toEqual([])
    await first.repository.saveProfile("a", defaultProfile)
    const mutation = h.calls.at(-1)!
    expect(mutation.body).toEqual({ expectedRevision: "2", profile: defaultProfile })
    expect(mutation.headers.get("x-csrf-token")).toBe("csrf-b")
  })

  it("does not read protected resources until email is verified", async () => {
    const h = harness(); h.setVerified(false)
    const loaded = await h.server().repository.loadSnapshot()
    expect(loaded.user?.emailVerified).toBe(false)
    expect(h.calls.map(c => c.path)).toEqual(["v1/auth/session"])
  })

  it("publishes the server result id, freezes the server profile revision and never writes client history", async () => {
    const h = harness(); const server = h.server(); await server.repository.loadSnapshot()
    const result = await server.api.analyzeVacancyWithContext!(input)
    expect(result.entry?.id).toBe("analysis-1")
    expect(h.calls.find(c => c.path === "v1/analysis-jobs")!.body).toEqual({ mode: "account", profileRevision: "2", vacancy: detectedJob, locale: "en" })
    const count = h.calls.length; await server.repository.addHistory(result.entry!)
    expect(h.calls).toHaveLength(count)
  })

  it("resumes an admitted job after reload without sending a second admission", async () => {
    const h = harness(); const first = h.server(); await first.repository.loadSnapshot()
    h.overrides.set("v1/jobs/job-1", () => Response.json({ jobId: "job-1", type: "analysis", status: "running" }))
    await expect(first.api.analyzeVacancy(input)).rejects.toMatchObject({ code: "poll_timeout" })
    h.overrides.delete("v1/jobs/job-1")
    const second = h.server(); await second.repository.loadSnapshot()
    expect((await second.resumeAnalysis())?.entry.id).toBe("analysis-1")
    expect(h.calls.filter(c => c.path === "v1/analysis-jobs")).toHaveLength(1)
    expect(second.hasPendingAnalysis()).toBe(false)
  })

  it("reuses the admission key when the server accepted a request but its response was lost", async () => {
    const h = harness(); const server = h.server(); await server.repository.loadSnapshot()
    h.overrides.set("v1/analysis-jobs", () => { throw new Error("response lost") })
    await expect(server.api.analyzeVacancy(input)).rejects.toMatchObject({ reason: "network" })
    h.overrides.delete("v1/analysis-jobs")
    await server.resumeAnalysis()
    const starts = h.calls.filter(c => c.path === "v1/analysis-jobs")
    expect(starts[0].headers.get("idempotency-key")).toBe(starts[1].headers.get("idempotency-key"))
  })

  it("clears terminal job failure and lets the next attempt use a new key", async () => {
    const h = harness(); const server = h.server(); await server.repository.loadSnapshot()
    h.overrides.set("v1/jobs/job-1", () => Response.json({ jobId: "job-1", type: "analysis", status: "failed", error: { code: "upstream" } }))
    await expect(server.api.analyzeVacancy(input)).rejects.toMatchObject({ code: "upstream" })
    expect(server.hasPendingAnalysis()).toBe(false)
  })

  it("surfaces quota and revision conflicts instead of overwriting or retrying a mutation", async () => {
    const h = harness(); const server = h.server(); await server.repository.loadSnapshot()
    h.overrides.set("v1/analysis-jobs", () => error(429, "quota_exceeded"))
    await expect(server.api.analyzeVacancy(input)).rejects.toBeInstanceOf(BackendApiError)
    expect(server.hasPendingAnalysis()).toBe(false)
    h.overrides.set("v1/profile", () => error(409, "profile_revision_conflict"))
    await expect(server.repository.saveProfile("a", defaultProfile)).rejects.toMatchObject({ code: "profile_revision_conflict" })
  })

  it("preserves the guest proof across registration, and claims with both CSRF proofs", async () => {
    const h = harness(); const server = h.server()
    await server.createGuest()
    const demo = await server.analyzeGuest(input)
    expect(demo.entry.userId).toBe("guest")
    await server.repository.createUser({ name: "a", email: "a@example.com", password: "long-password-123" })
    await server.claimGuest()
    const claim = h.calls.find(c => c.path === "v1/guest-claims")!
    expect(claim.headers.get("x-csrf-token")).toBe("csrf-a")
    expect(claim.headers.get("x-guest-csrf-token")).toBe("guest-proof")
    expect(server.hasGuestClaim()).toBe(false)
  })

  it("does not invent a profile for imported analyses with an absent snapshot", async () => {
    const h = harness()
    h.overrides.set("v1/history?limit=100", () => Response.json({ items: [{ ...resource, snapshot: { ...resource.snapshot, profileRevision: null, profile: null } }], hasMore: false, nextCursor: null }))
    expect((await h.server().repository.loadSnapshot()).history[0].profile).toBeNull()
  })

  it("preserves extraction metadata through review, draft persistence and admission", async () => {
    const { vacancyDraftSchema } = await import("./schemas")
    const h = harness(); const server = h.server(); await server.repository.loadSnapshot()
    const draft = vacancyDraftSchema.parse({ ...detectedJob, id: "metadata", sourceMode: "url", sourceUrl: "https://example.com/task", proposalCount: 248, averageBid: 50, averageBidCurrency: "USD", provenance: { proposalCount: "html" }, updatedAt: "2026-10-19T10:00:00Z" })
    await server.repository.saveDraft("a", draft)
    expect(h.calls.at(-1)!.body).toMatchObject({ vacancy: { proposalCount: 248, averageBid: 50, provenance: { proposalCount: "html" } } })
  })

  it("discards an in-flight old-account result if another session is loaded", async () => {
    const h = harness(); const server = h.server(); await server.repository.loadSnapshot()
    let complete!: (value: Response) => void
    h.overrides.set("v1/jobs/job-1", () => new Promise<Response>(resolve => { complete = resolve }))
    const pending = server.api.analyzeVacancy(input)
    const rejected = expect(pending).rejects.toMatchObject({ code: "session_changed" })
    await vi.waitFor(() => expect(complete).toBeTypeOf("function"))
    h.setAccount("b"); await server.repository.loadSnapshot()
    complete(Response.json({ jobId: "job-1", type: "analysis", status: "succeeded", analysisId: resource.analysisId, result: resource }))
    await rejected
  })

  it("rejects malformed successful responses before rendering a result", async () => {
    const h = harness(); const server = h.server(); await server.repository.loadSnapshot()
    h.overrides.set("v1/jobs/job-1", () => Response.json({ type: "analysis", status: "succeeded", result: { analysis: { score: 100 } } }))
    await expect(server.api.analyzeVacancy(input)).rejects.toMatchObject({ reason: "invalid_response" })
  })
})
