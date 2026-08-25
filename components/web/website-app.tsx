"use client"

import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import type { FitAnalysis, FreelancerProfile, Locale } from "@/lib/types"
import { resolveLocale } from "@/lib/i18n/locale"
import { getWebMessages } from "@/lib/i18n/web-messages"
import type { WebsiteApi } from "@/lib/web/api"
import { websiteApi } from "@/lib/web/api"
import { createWebsiteRepository, LocalAuthError } from "@/lib/web/repository"
import type { WebsiteRepository, WebsiteSnapshot } from "@/lib/web/types"
import type { VacancyDraft } from "@/lib/web/types"
import { createAnalysisRequest } from "@/lib/web/history"
import { AppShell, type WebView } from "./app-shell"
import { AuthScreen } from "./auth-screen"
import { LanguageSwitch } from "./language-switch"
import { ProfileEditor } from "./profile-editor"
import { VacancyReview } from "./vacancy-review"
import { VacancySource } from "./vacancy-source"

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
  const repositoryRef = useRef<WebsiteRepository | null>(null)
  if (!repositoryRef.current) {
    repositoryRef.current = repository ?? createWebsiteRepository()
  }
  const store = repositoryRef.current
  void api
  const [locale, setLocale] = useState<Locale>(initialLocale)
  const [snapshot, setSnapshot] = useState<WebsiteSnapshot>(emptySnapshot)
  const [initialized, setInitialized] = useState(false)
  const [busy, setBusy] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [view, setView] = useState<WebView>("analyze")
  const [analysisStep, setAnalysisStep] = useState<"source" | "review" | "analyzing" | "result">("source")
  const [draft, setDraft] = useState<VacancyDraft | null>(null)
  const [analysis, setAnalysis] = useState<FitAnalysis | null>(null)
  const copy = getWebMessages(locale)

  useEffect(() => {
    let active = true
    store
      .loadSnapshot()
      .then((loaded) => {
        if (!active) return
        setSnapshot(loaded)
        setDraft(loaded.draft)
        if (loaded.preferences) setLocale(loaded.preferences.locale)
        if (!loaded.profile) setView("profile")
      })
      .finally(() => active && setInitialized(true))
    return () => {
      active = false
    }
  }, [store])

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
    const result = await api.analyzeVacancy(
      createAnalysisRequest({
        profile: snapshot.profile,
        draft: nextDraft,
        locale,
        history: snapshot.history,
      }),
    )
    setAnalysis(result)
    setAnalysisStep("result")
  }

  function navigate(nextView: WebView) {
    setView(nextView === "analyze" && !snapshot.profile ? "profile" : nextView)
  }

  function content() {
    if (view === "profile") {
      return <ProfileEditor profile={snapshot.profile} copy={copy} onSave={saveProfile} />
    }
    if (view === "history") {
      return <section className="rounded-3xl border border-border bg-card p-8"><h1 className="text-3xl font-semibold">{copy.historyTitle}</h1><p className="mt-3 text-muted-foreground">{copy.noHistory}</p></section>
    }
    if (analysisStep === "review" && draft) {
      return <VacancyReview draft={draft} copy={copy} onBack={backToSource} onAnalyze={startAnalysis} />
    }
    if (analysisStep === "analyzing") {
      return <section className="grid min-h-96 place-items-center rounded-3xl border border-border bg-card"><p role="status" className="text-lg font-medium text-primary">{copy.analyzingVacancy}</p></section>
    }
    if (analysisStep === "result" && analysis) {
      return <section className="rounded-3xl border border-border bg-card p-10"><h1 className="text-3xl font-semibold">{draft?.title}</h1><p className="mt-6 text-5xl font-bold text-primary">{analysis.score} / 100</p><p className="mt-4 text-muted-foreground">{analysis.summary}</p><Button className="mt-6" onClick={() => setAnalysisStep("source")}>{copy.analyzeAnother}</Button></section>
    }
    return <VacancySource copy={copy} initialDraft={draft} onLoadUrl={api.extractVacancy} onReview={reviewDraft} />
  }

  if (!initialized) {
    return <main className="grid min-h-svh place-items-center bg-secondary"><p role="status" className="text-sm text-muted-foreground">{copy.loading}</p></main>
  }

  if (!snapshot.user) {
    return (
      <div className="relative">
        <div className="absolute right-4 top-4 z-10"><LanguageSwitch locale={locale} onChange={changeLocale} /></div>
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
