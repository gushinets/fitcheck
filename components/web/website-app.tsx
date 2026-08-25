"use client"

import { useEffect, useState } from "react"
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
}: {
  repository?: WebsiteRepository
  api?: WebsiteApi
}) {
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
        setLocale(loaded.preferences?.locale ?? initialLocale())
        if (!loaded.profile) setView("profile")
      })
      .finally(() => active && setInitialized(true))
    return () => {
      active = false
    }
  }, [store])

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
    setBusy(true)
    setAuthError(null)
    try {
      const user = await store.createUser(input)
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
    setBusy(true)
    setAuthError(null)
    try {
      await store.authenticate(input.email, input.password)
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
    await store.saveProfile(snapshot.user.id, profile)
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
    await store.saveDraft(snapshot.user.id, nextDraft)
    setDraft(nextDraft)
    setAnalysisStep("analyzing")
    setAnalysisError(null)
    try {
      const request = createAnalysisRequest({ profile: snapshot.profile, draft: nextDraft, locale, history: snapshot.history })
      const result = await api.analyzeVacancy(request)
      const entry = createHistoryEntry({ userId: snapshot.user.id, profile: snapshot.profile, job: request.job, analysis: result })
      await store.addHistory(entry)
      setSnapshot((current) => ({ ...current, history: [entry, ...current.history].slice(0, 50) }))
      setActiveEntry(entry)
      setAnalysisStep("result")
    } catch (error) {
      setAnalysisError(analysisErrorMessage(error))
      setAnalysisStep("review")
    }
  }

  function navigate(nextView: WebView) {
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
    try {
      return await api.suggestSkills(input)
    } catch (error) {
      throw new Error(skillSuggestionErrorMessage(error))
    }
  }

  async function saveFeedback(feedback: Omit<AnalysisFeedback, "createdAt">) {
    if (!snapshot.user || !activeEntry) return
    const saved = { ...feedback, createdAt: new Date().toISOString() }
    await store.saveFeedback(snapshot.user.id, activeEntry.id, saved)
    const update = (entry: WebHistoryEntry) => entry.id === activeEntry.id ? { ...entry, feedback: saved } : entry
    setSnapshot((current) => ({ ...current, history: current.history.map(update) }))
    setActiveEntry((current) => current ? update(current) : current)
  }

  function openHistory(entry: WebHistoryEntry) {
    const restoredDraft: VacancyDraft = {
      id: entry.job.id,
      sourceMode: entry.job.url ? "url" : "text",
      ...(entry.job.url ? { sourceUrl: entry.job.url } : {}),
      title: entry.job.title,
      description: entry.job.description,
      skills: entry.job.skills,
      ...(entry.job.hourlyRateMin === undefined ? {} : { hourlyRateMin: entry.job.hourlyRateMin }),
      ...(entry.job.hourlyRateMax === undefined ? {} : { hourlyRateMax: entry.job.hourlyRateMax }),
      ...(entry.job.fixedBudget === undefined ? {} : { fixedBudget: entry.job.fixedBudget }),
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

  async function deleteAccount() {
    if (!snapshot.user || !window.confirm(copy.deleteAccountConfirmation)) return
    await store.deleteUser(snapshot.user.id)
    setSnapshot(emptySnapshot)
    setDraft(null)
    setActiveEntry(null)
    setView("analyze")
    setAnalysisStep("source")
  }

  function content() {
    if (view === "profile") {
      return <div className="space-y-6"><ProfileEditor profile={snapshot.profile} locale={locale} copy={copy} onSave={saveProfile} onSuggestSkills={suggestProfileSkills} /><section className="mx-auto max-w-3xl rounded-3xl border border-danger/20 bg-card p-6 sm:p-8"><h2 className="text-lg font-semibold">{copy.localDataTitle}</h2><p className="mt-2 text-sm text-muted-foreground">{copy.localDataDescription}</p><p className="mt-3 text-sm font-medium">{snapshot.user?.email}</p><Button type="button" variant="destructive" className="mt-5" onClick={deleteAccount}>{copy.deleteAccount}</Button></section></div>
    }
    if (view === "history") {
      return <HistoryView entries={snapshot.history} locale={locale} copy={copy} onOpen={openHistory} onClear={async () => { if (window.confirm(copy.clearHistoryConfirmation) && snapshot.user) { await store.clearHistory(snapshot.user.id); setSnapshot((current) => ({ ...current, history: [] })) } }} />
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
    return <VacancySource copy={copy} initialDraft={draft} onLoadUrl={api.extractVacancy} onReview={reviewDraft} />
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
