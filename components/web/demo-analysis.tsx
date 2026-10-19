"use client"

import { useEffect, useState } from "react"
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

export function DemoAnalysis({ server, locale, onAccount }: { server: ServerWebsite; locale: Locale; onAccount: () => void }) {
  const copy = getWebMessages(locale)
  const ru = locale === "ru"
  const [ready, setReady] = useState(false)
  const [profile, setProfile] = useState<FreelancerProfile | null>(null)
  const [draft, setDraft] = useState<VacancyDraft | null>(null)
  const [result, setResult] = useState<WebHistoryEntry | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  async function initialize() {
    setError(""); setBusy(true)
    try {
      await server.createGuest(); setReady(true)
      if (server.hasPendingAnalysis()) { const resumed = await server.resumeAnalysis(); if (resumed) setResult(resumed.entry) }
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
    try { setResult((await server.analyzeGuest(createAnalysisRequest({ profile, draft: value, locale, history: [] }))).entry) }
    catch (e) { setError(serverErrorMessage(e, locale)) } finally { setBusy(false) }
  }
  return <main className="mx-auto max-w-6xl space-y-6 p-6">
    <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-xl font-semibold">{ru ? "Демо без регистрации" : "Try a demo"}</h1><Button variant="outline" disabled={busy} onClick={onAccount}>{ru ? "Создать аккаунт / войти" : "Create account / sign in"}</Button></div>
    <p>{ru ? "Лимит демо — один анализ. После подтверждения email результат можно сохранить в аккаунт." : "The demo allows one analysis. Verify your email to save the result to your account."}</p>
    {error ? <div role="alert" className="rounded-xl bg-danger-muted p-4">{error}{!ready ? <Button disabled={busy} onClick={initialize}>{copy.retry}</Button> : null}</div> : null}
    {busy ? <p role="status">{copy.analyzingVacancy}</p> : result ? <AnalysisResult entry={result} copy={copy} onBack={onAccount} onAnalyzeAnother={onAccount} onSaveFeedback={async () => { setError(ru ? "Сохраните демо в аккаунт, чтобы оставить исправление." : "Save the demo to an account to add feedback.") }} />
      : !ready ? null : !profile ? <ProfileEditor profile={null} locale={locale} copy={copy} onSave={async value => { setProfile(value) }} onSuggestSkills={async input => { try { return await server.api.suggestSkills(input) } catch (error) { throw new Error(serverErrorMessage(error, locale)) } }} />
      : draft ? <VacancyReview draft={draft} copy={copy} onBack={async () => setDraft(null)} onAnalyze={analyze} />
      : <VacancySource copy={copy} onLoadUrl={server.api.extractVacancy} onReview={setDraft} />}
  </main>
}
