"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import type { AnalysisFeedback, FreelancerProfile, Locale } from "@/lib/types"
import { resolveLocale } from "@/lib/i18n/locale"
import { getWebMessages } from "@/lib/i18n/web-messages"
import type { SkillSuggestionRequest } from "@/lib/skill-suggestions/schema"
import type { WebsiteApi } from "@/lib/web/api"
import { websiteApi } from "@/lib/web/api"
import { createWebsiteRepository, LocalAuthError } from "@/lib/web/repository"
import type { WebsiteRepository, WebsiteSnapshot } from "@/lib/web/types"
import type { VacancyDraft, WebHistoryEntry } from "@/lib/web/types"
import { createAnalysisRequest, createHistoryEntry } from "@/lib/web/history"
import { WebApiError } from "@/lib/web/api"
import { AppShell, type WebView } from "./app-shell"
import { AuthScreen } from "./auth-screen"
import { LanguageSwitch } from "./language-switch"
import { ProfileEditor } from "./profile-editor"
import { VacancyReview } from "./vacancy-review"
import { VacancySource } from "./vacancy-source"
import { AnalysisResult } from "./analysis-result"
import { HistoryView } from "./history-view"

import { createMetricsClient, deleteBrowserVisitor, sendBrowserMetrics } from "@/lib/metrics/client"
import { uuidSchema } from "@/lib/metrics/types"
import type { ClientContext, ClientEventName, ClientProperties } from "@/lib/metrics/types"

const noCampaignCodes: string[] = []
const emptySnapshot: WebsiteSnapshot = {
  user: null,
  profile: null,
  preferences: null,
  draft: null,
  history: [],
}

function initialLocale(): Locale {
  if (typeof window === "undefined") return "en"
  const stored = window.localStorage.getItem("fitcheck.locale")
  return stored === "ru" || stored === "en"
    ? stored
    : resolveLocale(window.navigator.language)
}

export function WebsiteApp({
  repository,
  api = websiteApi,
  metricsEnabled = false,
  knownCampaignCodes = noCampaignCodes,
}: {
  repository?: WebsiteRepository
  api?: WebsiteApi
  metricsEnabled?: boolean
  knownCampaignCodes?: string[]
}) {
  const metrics = useRef<ReturnType<typeof createMetricsClient> | null>(null)
  const observationGeneration = useRef(0)
  const viewedResults = useRef(new Set<string>())
  const campaignCodes = useRef(knownCampaignCodes)
  const observe = useCallback(<N extends ClientEventName,>(name: N, properties: ClientProperties[N], context?: ClientContext, generation = observationGeneration.current) => {
    if (generation !== observationGeneration.current) return
    try {
      if (context) metrics.current?.track(name, properties, context)
      else metrics.current?.track(name, properties)
    } catch { /* Telemetry cannot change product outcomes. */ }
  }, [])
  useEffect(() => {
    if (!metricsEnabled) return
    const client = createMetricsClient({ send: sendBrowserMetrics, deleteVisitor: deleteBrowserVisitor })
    metrics.current = client
    const generationRef = observationGeneration
    return () => {
      generationRef.current++
      if (metrics.current === client) metrics.current = null
      client.dispose()
    }
  }, [metricsEnabled])
  const [store] = useState<WebsiteRepository>(() =>
    repository ?? createWebsiteRepository(),
  )
  const [locale, setLocale] = useState<Locale>("en")
  const [snapshot, setSnapshot] = useState<WebsiteSnapshot>(emptySnapshot)
  const [initialized, setInitialized] = useState(false)
  const [busy, setBusy] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [view, setView] = useState<WebView>("analyze")
  const [analysisStep, setAnalysisStep] = useState<"source" | "review" | "analyzing" | "result">("source")
  const [draft, setDraft] = useState<VacancyDraft | null>(null)
  const [activeEntry, setActiveEntry] = useState<WebHistoryEntry | null>(null)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const copy = getWebMessages(locale)

  useEffect(() => {
    let active = true
    store
      .loadSnapshot()
      .then((loaded) => {
        if (!active) return
        setSnapshot(loaded)
        setDraft(loaded.draft)
        const loadedLocale = loaded.preferences?.locale ?? initialLocale()
        setLocale(loadedLocale)
        const rawCampaign = new URLSearchParams(window.location.search).get("utm_campaign")
        const campaign = rawCampaign === null ? "direct" : campaignCodes.current.includes(rawCampaign) && /^[a-z][a-z0-9_]{0,79}$/.test(rawCampaign) ? rawCampaign : "other"
        observe("page_viewed", { locale: loadedLocale, campaign })
        if (!loaded.profile) setView("profile")
      })
      .finally(() => active && setInitialized(true))
    return () => {
      active = false
    }
  }, [store, observe])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  async function refresh() {
    setSnapshot(await store.loadSnapshot())
  }

  async function createAccount(input: {
    name: string
    email: string
    password: string
  }) {
    const generation = observationGeneration.current
    setBusy(true)
    setAuthError(null)
    try {
      const user = await store.createUser(input)
      observe("local_registration_completed", { locale }, undefined, generation)
      await store.saveLocale(user.id, locale)
      await refresh()
      setView("profile")
    } catch (error) {
      setAuthError(authErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function signIn(input: { email: string; password: string }) {
    const generation = observationGeneration.current
    setBusy(true)
    setAuthError(null)
    try {
      await store.authenticate(input.email, input.password)
      observe("local_login_completed", { locale }, undefined, generation)
      await refresh()
    } catch (error) {
      setAuthError(authErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  function authErrorMessage(error: unknown) {
    if (!(error instanceof LocalAuthError)) return copy.authError
    return {
      duplicate_email: copy.duplicateEmail,
      unknown_email: copy.unknownEmail,
      incorrect_password: copy.incorrectPassword,
    }[error.code]
  }

  async function changeLocale(nextLocale: Locale) {
    setLocale(nextLocale)
    window.localStorage.setItem("fitcheck.locale", nextLocale)
    if (snapshot.user) {
      await store.saveLocale(snapshot.user.id, nextLocale)
      await refresh()
    }
  }

  async function saveProfile(profile: FreelancerProfile) {
    if (!snapshot.user) return
    const generation = observationGeneration.current
    await store.saveProfile(snapshot.user.id, profile)
    observe("profile_saved", { locale }, undefined, generation)
    await refresh()
    setView("analyze")
  }

  async function reviewDraft(nextDraft: VacancyDraft) {
    if (!snapshot.user) return
    await store.saveDraft(snapshot.user.id, nextDraft)
    setDraft(nextDraft)
    setAnalysisStep("review")
  }

  async function backToSource(nextDraft: VacancyDraft) {
    if (!snapshot.user) return
    await store.saveDraft(snapshot.user.id, nextDraft)
    setDraft(nextDraft)
    setAnalysisStep("source")
  }

  async function startAnalysis(nextDraft: VacancyDraft) {
    if (!snapshot.user || !snapshot.profile) return
    const generation = observationGeneration.current
    await store.saveDraft(snapshot.user.id, nextDraft)
    if (generation !== observationGeneration.current) return
    observe("analysis_requested", { locale, inputMode: nextDraft.sourceMode })
    setDraft(nextDraft)
    setAnalysisStep("analyzing")
    setAnalysisError(null)
    try {
      const request = createAnalysisRequest({ profile: snapshot.profile, draft: nextDraft, locale, history: snapshot.history })
      const result = api.analyzeVacancyWithContext
        ? await api.analyzeVacancyWithContext(request)
        : { analysis: await api.analyzeVacancy(request) }
      if (generation !== observationGeneration.current) return
      const entry = createHistoryEntry({ userId: snapshot.user.id, profile: snapshot.profile, job: request.job, analysis: result.analysis, providerOperationId: result.operationId })
      await store.addHistory(entry)
      if (generation !== observationGeneration.current) return
      setSnapshot((current) => ({ ...current, history: [entry, ...current.history].slice(0, 50) }))
      setActiveEntry(entry)
      setAnalysisStep("result")
    } catch (error) {
      if (generation !== observationGeneration.current) return
      setAnalysisError(analysisErrorMessage(error))
      setAnalysisStep("review")
    }
  }

  function navigate(nextView: WebView) {
    if (nextView === "history" && view !== "history") observe("history_viewed", {})
    setView(nextView === "analyze" && !snapshot.profile ? "profile" : nextView)
    if (nextView === "analyze") setAnalysisStep("source")
  }

  function analysisErrorMessage(error: unknown) {
    if (!(error instanceof WebApiError)) return copy.analysisFailed
    switch (error.code) {
      case "server_not_configured": return copy.serverNotConfigured
      case "analysis_rate_limit": return copy.analysisRateLimit
      case "analysis_timeout": return copy.analysisTimeout
      case "analysis_invalid_output": return copy.analysisInvalidOutput
      case "analysis_upstream": return copy.analysisUpstream
      case "origin_not_allowed": return copy.originNotAllowed
      case "network_error": return copy.networkError
      case "invalid_response": return copy.invalidResponse
      default: return copy.analysisFailed
    }
  }

  function skillSuggestionErrorMessage(error: unknown) {
    if (!(error instanceof WebApiError)) return copy.skillSuggestionsFailed
    switch (error.code) {
      case "suggestions_rate_limit": return copy.suggestionsRateLimit
      case "suggestions_timeout": return copy.suggestionsTimeout
      case "suggestions_invalid_output": return copy.suggestionsInvalidOutput
      case "suggestions_upstream": return copy.suggestionsUpstream
      case "server_not_configured": return copy.suggestionsServerNotConfigured
      case "network_error": return copy.suggestionsNetworkError
      case "invalid_response": return copy.suggestionsInvalidResponse
      default: return copy.skillSuggestionsFailed
    }
  }

  async function suggestProfileSkills(input: SkillSuggestionRequest) {
    observe("skills_requested", { locale })
    try {
      return await api.suggestSkills(input)
    } catch (error) {
      throw new Error(skillSuggestionErrorMessage(error))
    }
  }

  async function saveFeedback(feedback: Omit<AnalysisFeedback, "createdAt">) {
    if (!snapshot.user || !activeEntry) return
    const generation = observationGeneration.current
    const saved = { ...feedback, createdAt: new Date().toISOString() }
    await store.saveFeedback(snapshot.user.id, activeEntry.id, saved)
    observe("feedback_saved", { resultId: resultId(activeEntry), predictedScore: activeEntry.analysis.score, correctedScore: feedback.correctedScore }, resultContext(activeEntry), generation)
    const update = (entry: WebHistoryEntry) => entry.id === activeEntry.id ? { ...entry, feedback: saved } : entry
    setSnapshot((current) => ({ ...current, history: current.history.map(update) }))
    setActiveEntry((current) => current ? update(current) : current)
  }

  function resultId(entry: WebHistoryEntry) {
    return uuidSchema.safeParse(entry.providerOperationId).success ? entry.providerOperationId! : entry.id
  }
  function resultContext(entry: WebHistoryEntry): ClientContext {
    return uuidSchema.safeParse(entry.providerOperationId).success ? { operationId: entry.providerOperationId } : {}
  }
  useEffect(() => {
    if (view !== "analyze" || analysisStep !== "result" || !activeEntry) return
    const id = resultId(activeEntry)
    if (viewedResults.current.has(id)) return
    viewedResults.current.add(id)
    observe("analysis_result_viewed", { resultId: id, predictedScore: activeEntry.analysis.score }, resultContext(activeEntry))
  }, [view, analysisStep, activeEntry, observe])

  function openHistory(entry: WebHistoryEntry) {
    const restoredDraft: VacancyDraft = {
      id: entry.job.id,
      sourceMode: entry.job.url ? "url" : "text",
      ...(entry.job.url ? { sourceUrl: entry.job.url } : {}),
      title: entry.job.title,
      description: entry.job.description,
      skills: entry.job.skills,
      ...(entry.job.budgetCurrency ? { budgetCurrency: entry.job.budgetCurrency } : {}),
      ...(entry.job.hourlyRateMin === undefined ? {} : { hourlyRateMin: entry.job.hourlyRateMin }),
      ...(entry.job.hourlyRateMax === undefined ? {} : { hourlyRateMax: entry.job.hourlyRateMax }),
      ...(entry.job.fixedBudget === undefined ? {} : { fixedBudget: entry.job.fixedBudget }),
      ...(entry.job.fixedBudgetMax === undefined ? {} : { fixedBudgetMax: entry.job.fixedBudgetMax }),
      updatedAt: entry.createdAt,
    }
    setDraft(restoredDraft)
    setActiveEntry(entry)
    setAnalysisStep("result")
    setView("analyze")
  }

  async function analyzeAnother() {
    if (!snapshot.user) return
    await store.saveDraft(snapshot.user.id, null)
    setDraft(null)
    setActiveEntry(null)
    setAnalysisStep("source")
  }

  async function clearHistory() {
    if (!snapshot.user || !window.confirm(copy.clearHistoryConfirmation)) return
    const generation = observationGeneration.current
    await store.clearHistory(snapshot.user.id)
    observe("history_cleared", {}, undefined, generation)
    if (generation !== observationGeneration.current) return
    setSnapshot((current) => ({ ...current, history: [] }))
  }

  async function deleteAccount() {
    if (!snapshot.user || !window.confirm(copy.deleteAccountConfirmation)) return
    await store.deleteUser(snapshot.user.id)
    observe("local_account_deleted", {})
    observationGeneration.current++
    viewedResults.current.clear()
    // The bridge rotates the cookie even when journal deletion delivery fails.
    // Keep the owned client: deleteVisitor clears its old queue/session itself.
    const client = metrics.current
    void (async () => {
      try {
        const delivered = client ? await client.deleteVisitor() : await deleteBrowserVisitor()
        if (!delivered) console.info("FitCheck metrics: visitor deletion observation was not delivered")
      } catch { console.info("FitCheck metrics: visitor deletion observation was not delivered") }
    })()
    setSnapshot(emptySnapshot)
    setDraft(null)
    setActiveEntry(null)
    setView("analyze")
    setAnalysisStep("source")
  }

  function content() {
    if (view === "profile") {
      return <div className="space-y-6"><ProfileEditor profile={snapshot.profile} locale={locale} copy={copy} onSave={saveProfile} onSuggestSkills={suggestProfileSkills} onSkillsAccepted={(count) => observe("skills_accepted", { locale, count })} /><section className="mx-auto max-w-3xl rounded-3xl border border-danger/20 bg-card p-6 sm:p-8"><h2 className="text-lg font-semibold">{copy.localDataTitle}</h2><p className="mt-2 text-sm text-muted-foreground">{copy.localDataDescription}</p><p className="mt-3 text-sm font-medium">{snapshot.user?.email}</p><Button type="button" variant="destructive" className="mt-5" onClick={deleteAccount}>{copy.deleteAccount}</Button></section></div>
    }
    if (view === "history") {
      return <HistoryView entries={snapshot.history} locale={locale} copy={copy} onOpen={openHistory} onClear={clearHistory} />
    }
    if (analysisStep === "review" && draft) {
      return <div className="space-y-4">{analysisError ? <div role="alert" className="mx-auto max-w-4xl rounded-xl bg-danger-muted p-4 text-sm text-danger">{analysisError}</div> : null}<VacancyReview draft={draft} copy={copy} onBack={backToSource} onAnalyze={startAnalysis} /></div>
    }
    if (analysisStep === "analyzing") {
      return <section className="grid min-h-96 place-items-center rounded-3xl border border-border bg-card"><p role="status" className="text-lg font-medium text-primary">{copy.analyzingVacancy}</p></section>
    }
    if (analysisStep === "result" && activeEntry) {
      return <AnalysisResult entry={activeEntry} copy={copy} onBack={() => setAnalysisStep("source")} onAnalyzeAnother={analyzeAnother} onSaveFeedback={saveFeedback} />
    }
    return <VacancySource copy={copy} initialDraft={draft} onInputStarted={(inputMode) => observe("vacancy_input_started", { locale, inputMode })} onLoadUrl={(url) => { observe("extraction_requested", { locale, inputMode: "url" }); return api.extractVacancy(url) }} onReview={reviewDraft} />
  }

  if (!initialized) {
    return <main className="grid min-h-svh place-items-center bg-secondary"><p role="status" className="text-sm text-muted-foreground">{copy.loading}</p></main>
  }

  if (!snapshot.user) {
    return (
      <div className="relative">
        <div className="absolute right-4 top-4 z-10"><LanguageSwitch locale={locale} label={copy.language} onChange={changeLocale} /></div>
        <AuthScreen copy={copy} error={authError} busy={busy} onCreate={createAccount} onSignIn={signIn} />
      </div>
    )
  }

  return (
    <AppShell user={snapshot.user} locale={locale} copy={copy} activeView={view} onNavigate={navigate} onLocaleChange={changeLocale} onSignOut={async () => { await store.signOut(); setSnapshot(emptySnapshot); setView("analyze") }}>
      {content()}
    </AppShell>
  )
}
