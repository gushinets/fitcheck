import { z } from "zod"
import { BackendApiError, createBackendClient } from "@/lib/backend/client"
import type { AnalysisRequest, Locale } from "@/lib/types"
import type { WebsiteApi } from "./api"
import type { HistoryFilters, LocalUser, VacancyDraft, WebHistoryEntry, WebsiteRepository, WebsiteSnapshot } from "./types"
import { draftToJob } from "./history"
import { createWebsiteRepository } from "./repository"
import { batchLocalExport } from "./local-export"
import * as s from "./server-contracts"

const empty = (): WebsiteSnapshot => ({ user: null, profile: null, preferences: null, draft: null, history: [] })
const voidSchema = z.undefined()
export class WebsiteServerError extends Error {
  constructor(public readonly code: string) { super(code) }
}
const storage = () => typeof window === "undefined" ? undefined : window.localStorage
const guestStorage = () => typeof window === "undefined" ? undefined : window.sessionStorage
function read(key: string) { try { return storage()?.getItem(key) ?? null } catch { return null } }
function write(key: string, value: string | null) {
  try { if (value === null) storage()?.removeItem(key); else storage()?.setItem(key, value) } catch { /* Server jobs remain available in history. */ }
}

export function createServerWebsite(config: { fetch?: typeof fetch; delay?: () => Promise<void>; maxPolls?: number } = {}) {
  const client = createBackendClient({ baseUrl: "/api/backend", fetch: config.fetch })
  let csrf: string | null = null
  let user: LocalUser | null = null
  let revision: string | null = null
  let locale: Locale = "en"
  let generation = 0
  let pendingGeneration = 0
  const delay = config.delay ?? (() => new Promise<void>(resolve => setTimeout(resolve, 1500)))
  async function request<T>(path: string, schema: z.ZodType<T>, method = "GET", body?: unknown, extra?: Record<string, string>) {
    const started = generation
    try {
      const value = await client.request(path, { method, body, headers: { ...(csrf ? { "X-CSRF-Token": csrf } : {}), ...extra }, validate: value => schema.parse(value) })
      if (started !== generation) throw new WebsiteServerError("session_changed")
      return value
    } catch (error) {
      if (started !== generation) throw new WebsiteServerError("session_changed")
      throw error
    }
  }
  const pendingKey = () => `fitcheck.pending-analysis.${user?.id ?? "guest"}`
  function reset() { generation++; csrf = null; user = null; revision = null }
  async function bootstrap() { return request("v1/auth/csrf", s.csrfSchema) }
  function setSession(session: z.infer<typeof s.sessionSchema>) {
    if (user && user.id !== session.user.id) generation++
    csrf = session.csrfToken
    user = { ...session.user, name: session.user.email.split("@")[0], createdAt: "" }
    return user
  }
  async function authenticate(path: string, email: string, password: string) {
    reset()
    csrf = (await bootstrap()).csrfToken
    return setSession(await request(path, s.sessionSchema, "POST", { email, password }))
  }
  async function poll(jobId: string) {
    const started = generation
    for (let i = 0; i < (config.maxPolls ?? 200); i++) {
      if (generation !== started) throw new WebsiteServerError("session_changed")
      const job = await request(`v1/jobs/${encodeURIComponent(jobId)}`, s.jobStateSchema)
      if (generation !== started) throw new WebsiteServerError("session_changed")
      if (job.status === "failed") throw new WebsiteServerError(job.error.code)
      if (job.status === "succeeded") return job
      await delay()
    }
    throw new WebsiteServerError("poll_timeout")
  }
  function entry(resource: s.ServerAnalysisResource): WebHistoryEntry {
    return {
      id: resource.analysisId, userId: user?.id ?? "guest", profile: resource.snapshot.profile ?? null,
      profileRevision: resource.snapshot.profileRevision, profileChanged: resource.profileChanged, job: resource.snapshot.vacancy,
      analysis: resource.analysis, createdAt: resource.createdAt, applicationStatus: resource.applicationStatus,
      ...(resource.feedback ? { feedback: { ...resource.feedback, createdAt: resource.createdAt } } : {}),
    }
  }
  function draft(resource: z.infer<typeof s.draftResourceSchema>): VacancyDraft | null {
    if (!resource) return null
    return { ...resource.vacancy, sourceMode: resource.vacancy.url ? "url" : "text", sourceUrl: resource.vacancy.url, updatedAt: new Date().toISOString() }
  }
  async function completed(jobId: string, receipt: string | null) {
    const key = pendingKey()
    const clear = () => { if (read(key) === receipt) write(key, null) }
    let job
    try { job = await poll(jobId) } catch (error) {
      if (error instanceof WebsiteServerError && error.code !== "poll_timeout" && error.code !== "session_changed" || error instanceof BackendApiError && [400, 403, 404, 410].includes(error.status)) clear()
      throw error
    }
    if (job.type !== "analysis") throw new WebsiteServerError("invalid_response")
    clear()
    return { analysis: job.result.analysis, entry: entry(job.result) }
  }
  async function analyze(input: AnalysisRequest, guest = false) {
    const started = generation
    // Persist the admission key before sending: a lost response retries the same job.
    const key = pendingKey()
    const existing = read(key)
    if (existing) {
      const saved = z.object({ key: z.string(), body: z.unknown(), jobId: z.string().optional() }).safeParse(JSON.parse(existing))
      if (saved.success) {
        const jobId = saved.data.jobId ?? (await request("v1/analysis-jobs", s.admissionSchema, "POST", saved.data.body, { "Idempotency-Key": saved.data.key })).jobId
        return completed(jobId, existing)
      }
    }
    const body = guest ? { mode: "guest", vacancy: input.job, profile: input.profile, locale: input.locale }
      : { mode: "account", vacancy: input.job, profileRevision: revision, locale: input.locale }
    const pending = { key: crypto.randomUUID(), body }
    let receipt = JSON.stringify(pending)
    write(key, receipt)
    try {
      const admitted = await request("v1/analysis-jobs", s.admissionSchema, "POST", body, { "Idempotency-Key": pending.key })
      if (generation !== started) throw new WebsiteServerError("session_changed")
      // A user may have started another task while admission was in flight.
      // The old request owns only its receipt, never the newer recovery record.
      if (read(key) === receipt) {
        receipt = JSON.stringify({ ...pending, jobId: admitted.jobId })
        write(key, receipt)
      }
      return await completed(admitted.jobId, receipt)
    } catch (error) {
      // Transport failures/timeouts retain admission proof for an explicit retry.
      if (read(key) === receipt && (error instanceof BackendApiError && error.status < 500 || error instanceof WebsiteServerError && error.code !== "poll_timeout" && error.code !== "session_changed")) write(key, null)
      throw error
    }
  }
  async function loadHistory(cursor?: string | null, filters: Partial<HistoryFilters> = {}) {
    const params = new URLSearchParams({ limit: "100" })
    if (cursor) params.set("cursor", cursor)
    if (filters.applicationStatus) params.set("applicationStatus", filters.applicationStatus)
    if (filters.verdict) params.set("verdict", filters.verdict)
    const page = await request(`v1/history?${params}`, s.historyPageSchema)
    return { history: page.items.map(entry), historyCursor: page.nextCursor }
  }
  const repository: WebsiteRepository = {
    exportLocalData: id => createWebsiteRepository().exportLocalData(id),
    createUser: input => authenticate("v1/auth/register", input.email, input.password),
    authenticate: (email, password) => authenticate("v1/auth/login", email, password),
    async loadSnapshot(historyFilters) {
      let started = generation
      let session
      try { session = await request("v1/auth/session", s.sessionSchema) } catch (error) {
        if (error instanceof BackendApiError && error.status === 401) { reset(); return empty() }
        throw error
      }
      if (started !== generation) throw new WebsiteServerError("session_changed")
      setSession(session)
      started = generation
      if (!user!.emailVerified) return { ...empty(), user }
      const [profile, preferences, savedDraft, page] = await Promise.all([
        request("v1/profile", s.profileResourceSchema).catch(error => {
          if (error instanceof BackendApiError && error.code === "not_found") return null
          throw error
        }),
        request("v1/preferences", s.preferencesSchema), request("v1/draft", s.draftResourceSchema),
        loadHistory(null, historyFilters),
      ])
      if (started !== generation) throw new WebsiteServerError("session_changed")
      revision = profile?.revision ?? null
      locale = preferences.locale
      return { user, profile: profile?.profile ?? null, preferences: { userId: user!.id, ...preferences }, draft: draft(savedDraft), ...page }
    },
    async signOut() {
      const key = pendingKey()
      await request("v1/auth/logout", voidSchema, "POST")
      write(key, null); reset()
    },
    async saveLocale(_id, value) { await request("v1/preferences", s.preferencesSchema, "PUT", { locale: value }); locale = value },
    async saveProfile(_id, profile) {
      const resource = await request("v1/profile", s.profileResourceSchema, "PUT", { profile, expectedRevision: revision })
      revision = resource.revision
    },
    async saveDraft(_id, value) { await request("v1/draft", s.draftResourceSchema, "PUT", value ? { vacancy: draftToJob(value), locale } : null) },
    // Analysis publication is atomic on the server; clients never write a result.
    async addHistory() {},
    async saveFeedback(_id, id, feedback) {
      await request(`v1/analyses/${encodeURIComponent(id)}/feedback`, z.unknown(), "PUT", { correctedScore: feedback.correctedScore, ...(feedback.note ? { note: feedback.note } : {}) })
    },
    async clearHistory() { await request("v1/history", voidSchema, "DELETE") },
    async deleteUser(_id, password) {
      await request("v1/me", voidSchema, "DELETE", { password })
      write(pendingKey(), null); reset()
    },
  }
  const api: WebsiteApi = {
    async extractVacancy(url) {
      const resource = await request("v1/extractions", z.object({ vacancy: s.serverVacancySchema }), "POST", { type: "url", url })
      return { ...resource.vacancy, sourceMode: "url", sourceUrl: url, updatedAt: new Date().toISOString() }
    },
    analyzeVacancy: async input => (await analyze(input)).analysis,
    analyzeVacancyWithContext: input => analyze(input),
    async suggestSkills(input) {
      const admitted = await request("v1/skill-suggestion-jobs", s.admissionSchema, "POST", input, { "Idempotency-Key": crypto.randomUUID() })
      const job = await poll(admitted.jobId)
      if (job.type !== "skill_suggestions") throw new WebsiteServerError("invalid_response")
      return job.skills
    },
  }
  return {
    repository, api,
    hasPendingAnalysis: () => Boolean(read(pendingKey())),
    async resumeAnalysis() {
      const value = read(pendingKey())
      if (!value) return null
      const saved = JSON.parse(value)
      const jobId = saved.jobId ?? (await request("v1/analysis-jobs", s.admissionSchema, "POST", saved.body, { "Idempotency-Key": saved.key })).jobId
      return completed(jobId, value)
    },
    forgetPendingAnalysis() { pendingGeneration++; write(pendingKey(), null) },
    loadHistory,
    async setApplicationStatus(id: string, applicationStatus: NonNullable<WebHistoryEntry["applicationStatus"]>) {
      await request(`v1/analyses/${encodeURIComponent(id)}/application-status`, z.unknown(), "PUT", { applicationStatus })
    },
    async reanalyze(id: string) {
      const started = pendingGeneration
      const key = pendingKey()
      const previous = read(key)
      const admitted = await request(`v1/analyses/${encodeURIComponent(id)}/reanalyses`, s.admissionSchema, "POST", {}, { "Idempotency-Key": crypto.randomUUID() })
      const receipt = JSON.stringify({ jobId: admitted.jobId })
      if (started === pendingGeneration && read(key) === previous) write(key, receipt)
      return completed(admitted.jobId, receipt)
    },
    requestVerification: (email: string) => request("v1/auth/verify-email/request", voidSchema, "POST", { email }),
    verifyEmail: (token: string) => request("v1/auth/verify-email", voidSchema, "POST", { token }),
    requestPasswordReset: (email: string) => request("v1/auth/password-reset/request", voidSchema, "POST", { email }),
    confirmPasswordReset: (token: string, password: string) => request("v1/auth/password-reset/confirm", voidSchema, "POST", { token, password }),
    async createGuest() {
      reset(); csrf = (await bootstrap()).csrfToken
      const session = await request("v1/guest-sessions", s.csrfSchema, "POST")
      csrf = session.csrfToken
      guestStorage()?.setItem("fitcheck.guest-csrf", csrf)
    },
    analyzeGuest: (input: AnalysisRequest) => analyze(input, true),
    hasGuestClaim: () => Boolean(guestStorage()?.getItem("fitcheck.guest-csrf")),
    async claimGuest() {
      const guestCsrf = guestStorage()?.getItem("fitcheck.guest-csrf")
      if (!guestCsrf) return
      let key = guestStorage()?.getItem("fitcheck.claim-key")
      if (!key) { key = crypto.randomUUID(); guestStorage()?.setItem("fitcheck.claim-key", key) }
      await request("v1/guest-claims", z.object({ claimedCount: z.number(), profileImported: z.boolean() }), "POST", {}, { "X-Guest-CSRF-Token": guestCsrf, "Idempotency-Key": key })
      guestStorage()?.removeItem("fitcheck.guest-csrf"); guestStorage()?.removeItem("fitcheck.claim-key")
      write("fitcheck.pending-analysis.guest", null)
    },
    async importLocal(email: string, password: string) {
      const legacy = createWebsiteRepository()
      const selected = await legacy.authenticate(email, password)
      const started = generation
      const batches = batchLocalExport(await legacy.exportLocalData(selected.id), 900_000)
      const total = { importedCount: 0, skippedCount: 0, conflictCount: 0, invalidCount: 0 }
      for (const body of batches) {
        if (started !== generation) throw new WebsiteServerError("session_changed")
        const fingerprint = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(body))))).map(v => v.toString(16).padStart(2, "0")).join("")
        const admitted = await request("v1/import-jobs", z.object({ importId: z.string() }), "POST", body, { "Idempotency-Key": `website-import-${fingerprint}` })
        let finished = false
        for (let i = 0; i < (config.maxPolls ?? 200); i++) {
          if (started !== generation) throw new WebsiteServerError("session_changed")
          const state = await request(`v1/import-jobs/${admitted.importId}`, s.importStateSchema)
          if (state.status === "failed") throw new WebsiteServerError(state.error?.code ?? "import_failed")
          if (state.status === "succeeded" && state.report) {
            for (const field of ["importedCount", "skippedCount", "conflictCount", "invalidCount"] as const) total[field] += state.report[field]
            finished = true; break
          }
          await delay()
        }
        if (!finished) throw new WebsiteServerError("poll_timeout")
      }
      return total
    },
  }
}
export type ServerWebsite = ReturnType<typeof createServerWebsite>
