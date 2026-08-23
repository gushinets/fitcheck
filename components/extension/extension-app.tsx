"use client"

import { useCallback, useEffect, useState } from "react"
import { AppHeader } from "./app-header"
import { BottomNavigation } from "./bottom-navigation"
import { DetailsScreen } from "./details-screen"
import { EmptyState } from "./empty-state"
import { ErrorState } from "./error-state"
import { HistoryScreen } from "./history-screen"
import { FeedbackScreen } from "./feedback-screen"
import { LoadingState } from "./loading-state"
import { Onboarding } from "./onboarding"
import { ProfileScreen } from "./profile-screen"
import { ReadyScreen } from "./ready-screen"
import { ResultScreen } from "./result-screen"
import { getMessages } from "@/lib/i18n/messages"
import type { ExtensionRuntime } from "@/lib/extension/runtime"
import type { AnalyzeState, FitAnalysis, FreelancerProfile, HistoryEntry, Job, Locale, Tab } from "@/lib/types"

interface ExtensionAppProps { runtime: ExtensionRuntime; previewControls?: boolean }

function calibrationMemory(history: HistoryEntry[]) {
  return history.slice(0, 10).map((entry) => ({
    jobTitle: entry.job.title,
    predictedScore: entry.analysis.score,
    ...(entry.feedback ? {
      correctedScore: entry.feedback.correctedScore,
      ...(entry.feedback.note ? { note: entry.feedback.note } : {}),
    } : {}),
  }))
}

export function ExtensionApp({ runtime, previewControls = false }: ExtensionAppProps) {
  const [initialized, setInitialized] = useState(false)
  const [locale, setLocale] = useState<Locale>("en")
  const [profile, setProfile] = useState<FreelancerProfile | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [analysis, setAnalysis] = useState<FitAnalysis | null>(null)
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>("analyze")
  const [analyzeState, setAnalyzeState] = useState<AnalyzeState>("ready")

  const loadJob = useCallback(async () => {
    const result = await runtime.getCurrentJob()
    if (!result.ok) {
      setJob(null)
      setAnalyzeState(result.reason === "unsupported" ? "unsupported" : "error")
      return
    }
    setJob(result.job)
    setAnalyzeState("ready")
  }, [runtime])

  useEffect(() => {
    let active = true
    Promise.all([runtime.getLocale(), runtime.loadState(), runtime.getCurrentJob()])
      .then(([nextLocale, state, jobResult]) => {
        if (!active) return
        setLocale(nextLocale)
        setProfile(state.profile)
        setHistory(state.history)
        if (jobResult.ok) {
          setJob(jobResult.job)
          setAnalyzeState("ready")
        } else {
          setAnalyzeState(jobResult.reason === "unsupported" ? "unsupported" : "error")
        }
      })
      .catch(() => active && setAnalyzeState("error"))
      .finally(() => active && setInitialized(true))
    return () => { active = false }
  }, [runtime])

  async function saveProfile(nextProfile: FreelancerProfile) {
    await runtime.saveProfile(nextProfile)
    setProfile(nextProfile)
    setTab("analyze")
    await loadJob()
  }

  async function startAnalysis() {
    if (!profile || !job) return
    setAnalyzeState("loading")
    try {
      const result = await runtime.analyze({ profile, job, locale, memory: calibrationMemory(history) })
      const now = new Date()
      const entry: HistoryEntry = {
        id: `${job.id}-${now.getTime()}`,
        jobTitle: job.title,
        score: result.score,
        status: result.status,
        timestamp: now.toLocaleString(locale),
        createdAt: now.toISOString(),
        analysis: result,
        job,
      }
      await runtime.addAnalysis(entry)
      setHistory((current) => [entry, ...current].slice(0, 50))
      setAnalysis(result)
      setActiveEntryId(entry.id)
      setAnalyzeState("result")
    } catch {
      setAnalyzeState("error")
    }
  }

  function openHistoryEntry(entry: HistoryEntry) {
    setJob(entry.job)
    setAnalysis(entry.analysis)
    setActiveEntryId(entry.id)
    setTab("analyze")
    setAnalyzeState("result")
  }

  const copy = getMessages(locale)

  function analyzeBody() {
    if (analyzeState === "loading") return <LoadingState copy={copy} />
    if (analyzeState === "unsupported") {
      return <EmptyState title={copy.unsupportedTitle} description={copy.unsupportedDescription} />
    }
    if (analyzeState === "error") return <ErrorState onRetry={loadJob} copy={copy} />
    if (!job) return <LoadingState copy={copy} />
    if (analyzeState === "feedback" && analysis && activeEntryId) {
      return (
        <FeedbackScreen
          analysis={analysis}
          copy={copy}
          onCancel={() => setAnalyzeState("result")}
          onSave={async (feedback) => {
            const saved = { ...feedback, createdAt: new Date().toISOString() }
            await runtime.saveFeedback(activeEntryId, saved)
            setHistory((current) => current.map((entry) => entry.id === activeEntryId ? { ...entry, feedback: saved } : entry))
            setAnalyzeState("result")
          }}
        />
      )
    }
    if (analyzeState === "result" && analysis) {
      return <ResultScreen job={job} analysis={analysis} copy={copy} onViewDetails={() => setAnalyzeState("details")} onInaccurate={() => setAnalyzeState("feedback")} onApply={() => void runtime.applyToJob()} onSkip={runtime.closePopup} />
    }
    if (analyzeState === "details" && analysis) {
      return <DetailsScreen job={job} analysis={analysis} copy={copy} onBack={() => setAnalyzeState("result")} />
    }
    return <ReadyScreen job={job} profile={profile!} copy={copy} onAnalyze={startAnalysis} />
  }

  function body() {
    if (!initialized) return <LoadingState copy={copy} />
    if (!profile) return <Onboarding onSave={saveProfile} copy={copy} />
    if (tab === "history") return <HistoryScreen entries={history} onOpen={openHistoryEntry} copy={copy} onClear={async () => { if (window.confirm(copy.clearHistory)) { await runtime.clearHistory(); setHistory([]) } }} />
    if (tab === "profile") {
      return <ProfileScreen profile={profile} copy={copy} onSave={saveProfile} onReset={async () => { if (window.confirm(copy.resetProfile)) { await runtime.resetProfile(); setProfile(null) } }} />
    }
    return analyzeBody()
  }

  const chrome = (
    <div className="flex h-[600px] w-[400px] max-w-full flex-col overflow-hidden bg-background">
      {profile ? <AppHeader subtitle={copy.appSubtitle} /> : null}
      <div className="flex min-h-0 flex-1 flex-col">{body()}</div>
      {profile ? <BottomNavigation active={tab} onChange={setTab} copy={copy} /> : null}
    </div>
  )
  if (!previewControls) return chrome
  return <main className="flex min-h-svh flex-col items-center justify-center bg-secondary px-4 py-8"><div className="overflow-hidden rounded-2xl border border-border shadow-xl shadow-black/5">{chrome}</div></main>
}
