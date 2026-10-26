"use client"

import { useEffect, useRef, useState } from "react"
import type { MetricsObserver } from "@/lib/metrics/types"
import { Button } from "@/components/ui/button"
import type { FreelancerProfile, Locale } from "@/lib/types"
import type { ServerWebsite } from "@/lib/web/server"
import { serverErrorMessage } from "@/lib/web/server-errors"
import { getWebMessages } from "@/lib/i18n/web-messages"
import { createAnalysisRequest } from "@/lib/web/history"
import type { VacancyDraft, WebHistoryEntry } from "@/lib/web/types"
import { ProfileEditor } from "./profile-editor"
import { VacancySource } from "./vacancy-source"
import { VacancyReview } from "./vacancy-review"
import { AnalysisResult } from "./analysis-result"

export function DemoAnalysis({ server, locale, onAccount, observe }: { server: ServerWebsite; locale: Locale; onAccount: () => void; observe?: MetricsObserver }) {
  const copy = getWebMessages(locale)
  const ru = locale === "ru"
  const [ready, setReady] = useState(false)
  const [profile, setProfile] = useState<FreelancerProfile | null>(null)
  const [draft, setDraft] = useState<VacancyDraft | null>(null)
  const [result, setResult] = useState<WebHistoryEntry | null>(null)
  const [jobId, setJobId] = useState<string | undefined>()
  const viewed = useRef(new Set<string>())
  const inputMode = useRef<"text" | "url">("text")
  function track(...args: Parameters<MetricsObserver>) { try { observe?.(...args) } catch { /* Best effort observations. */ } }
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!result || busy) return
    const entry = result
    function observeVisibleResult() {
      if (document.visibilityState !== "visible" || viewed.current.has(entry.id)) return
      viewed.current.add(entry.id)
      try { observe?.("analysis_result_viewed", { flow: "demo", locale, inputMode: inputMode.current, resultId: entry.id, predictedScore: entry.analysis.score }, { operationId: jobId }) } catch { /* Best effort observations. */ }
    }
    observeVisibleResult()
    document.addEventListener("visibilitychange", observeVisibleResult)
    return () => document.removeEventListener("visibilitychange", observeVisibleResult)
  }, [result, busy, locale, jobId, observe])
  const [error, setError] = useState("")
  async function initialize() {
    setError(""); setBusy(true)
    try {
      await server.createGuest(); setReady(true)
      if (server.hasPendingAnalysis()) { const resumed = await server.resumeAnalysis(); if (resumed) { inputMode.current = resumed.entry.job.url ? "url" : "text"; setJobId(resumed.jobId); setResult(resumed.entry) } }
    } catch (e) { setError(serverErrorMessage(e, locale)) } finally { setBusy(false) }
  }
  // A guest session is issued once on entry; the backend reuses an existing cookie.
  useEffect(() => {
    const timer = setTimeout(() => { void initialize() }, 0)
    return () => clearTimeout(timer)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  async function analyze(value: VacancyDraft) {
    if (!profile) return
    setBusy(true); setError("")
    inputMode.current = value.sourceMode
    try {
      const completed = await server.analyzeGuest(createAnalysisRequest({ profile, draft: value, locale, history: [] }),
        requestId => track("analysis_requested", { flow: "demo", locale, inputMode: value.sourceMode, requestId }))
      setJobId(completed.jobId); setResult(completed.entry)
    }
    catch (e) { setError(serverErrorMessage(e, locale)) } finally { setBusy(false) }
  }
  return <main className="mx-auto max-w-6xl space-y-6 p-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-xl font-semibold">{ru ? "Демо без регистрации" : "Try a demo"}</h1><Button variant="outline" disabled={busy} onClick={onAccount}>{ru ? "Создать аккаунт / войти" : "Create account / sign in"}</Button></div>
    <p>{ru ? "Лимит демо — один анализ. После подтверждения email результат можно сохранить в аккаунт." : "The demo allows one analysis. Verify your email to save the result to your account."}</p>
    {error ? <div role="alert" className="rounded-xl bg-danger-muted p-4">{error}{!ready ? <Button disabled={busy} onClick={initialize}>{copy.retry}</Button> : null}</div> : null}
    {busy ? <p role="status">{copy.analyzingVacancy}</p> : result ? <AnalysisResult entry={result} copy={copy} onBack={onAccount} onAnalyzeAnother={onAccount} onSaveFeedback={async () => { setError(ru ? "Сохраните демо в аккаунт, чтобы оставить исправление." : "Save the demo to an account to add feedback.") }} />
      : !ready ? null : !profile ? <ProfileEditor profile={null} locale={locale} copy={copy} onSave={async value => { setProfile(value) }} onSuggestSkills={async input => { try { return await server.api.suggestSkills(input) } catch (error) { throw new Error(serverErrorMessage(error, locale)) } }} />
      : draft ? <VacancyReview draft={draft} copy={copy} onBack={async () => setDraft(null)} onAnalyze={analyze} />
      : <VacancySource copy={copy} onInputStarted={inputMode => track("vacancy_input_started", { flow: "demo", locale, inputMode })} onLoadUrl={url => { track("extraction_requested", { flow: "demo", locale, inputMode: "url" }); return server.api.extractVacancy(url) }} onReview={setDraft} />}
  </main>
}
