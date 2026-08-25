"use client"

import { useState } from "react"
import { ArrowLeft, CheckCircle2, RotateCcw, TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { WebMessages } from "@/lib/i18n/web-messages"
import type { WebHistoryEntry } from "@/lib/web/types"

export function AnalysisResult({
  entry,
  copy,
  onBack,
  onAnalyzeAnother,
  onSaveFeedback,
}: {
  entry: WebHistoryEntry
  copy: WebMessages
  onBack: () => void
  onAnalyzeAnother: () => void
  onSaveFeedback: (feedback: { correctedScore: number; note?: string }) => void
}) {
  const [correcting, setCorrecting] = useState(false)
  const [score, setScore] = useState(String(entry.feedback?.correctedScore ?? entry.analysis.score))
  const [note, setNote] = useState(entry.feedback?.note ?? "")
  const analysis = entry.analysis
  const isGo = analysis.status === "GO"
  const breakdown = [
    [copy.skills, analysis.breakdown.skills],
    [copy.experience, analysis.breakdown.experience],
    [copy.rate, analysis.breakdown.rate],
    [copy.english, analysis.breakdown.english],
    [copy.requirements, analysis.breakdown.requirements],
  ] as const

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline">
          <ArrowLeft className="size-4" aria-hidden="true" />{copy.backToSelection}
        </button>
        <Button variant="outline" onClick={onAnalyzeAnother}><RotateCcw className="size-4" aria-hidden="true" />{copy.analyzeAnother}</Button>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(20rem,0.95fr)]">
        <div className="space-y-6">
          <div className="rounded-3xl border border-border bg-card p-6 shadow-sm sm:p-8">
            <p className="text-sm font-medium text-muted-foreground">{entry.job.title}</p>
            <div className="mt-6 flex flex-col gap-6 sm:flex-row sm:items-center">
              <div aria-label={`${copy.fitScore} ${analysis.score} ${copy.outOf100}`} className={`grid size-40 shrink-0 place-items-center rounded-full border-[12px] ${isGo ? "border-success-muted bg-success-muted/30" : "border-warning-muted bg-warning-muted/30"}`}>
                <div className="text-center"><div className="text-5xl font-bold tracking-tight">{analysis.score}</div><div className="text-xs text-muted-foreground">/ 100</div></div>
              </div>
              <div>
                <span className={`inline-flex rounded-full px-3 py-1 text-xs font-bold ${isGo ? "bg-success-muted text-success" : "bg-warning-muted text-warning-foreground"}`}>{isGo ? copy.go : copy.noGo}</span>
                <h1 className="mt-3 text-3xl font-semibold tracking-tight">{analysis.label}</h1>
                <p className="mt-3 leading-7 text-muted-foreground">{analysis.summary}</p>
              </div>
            </div>
          </div>
          <div className="rounded-3xl border border-border bg-card p-6 shadow-sm sm:p-8">
            <h2 className="text-xl font-semibold">{copy.fitBreakdown}</h2>
            <div className="mt-6 space-y-4">
              {breakdown.map(([label, value]) => (
                <div key={label}>
                  <div className="mb-2 flex justify-between text-sm"><span>{label}</span><strong>{value}</strong></div>
                  <div className="h-2 overflow-hidden rounded-full bg-secondary"><div className="h-full rounded-full bg-primary" style={{ width: `${value}%` }} /></div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="space-y-6">
          <ListCard title={copy.strengths} items={analysis.strengths} tone="success" />
          <ListCard title={copy.risks} items={analysis.risks} tone="warning" />
          <div className="rounded-3xl border border-border bg-card p-6 shadow-sm">
            {!correcting ? (
              <Button variant="outline" className="w-full" onClick={() => setCorrecting(true)}>{copy.correctScore}</Button>
            ) : (
              <form onSubmit={(event) => { event.preventDefault(); const correctedScore = Number(score); if (correctedScore >= 0 && correctedScore <= 100) { onSaveFeedback({ correctedScore, ...(note.trim() ? { note: note.trim() } : {}) }); setCorrecting(false) } }} className="space-y-4">
                <div className="space-y-1.5"><Label htmlFor="corrected-score">{copy.correctedScore}</Label><Input id="corrected-score" type="number" min={0} max={100} value={score} onChange={(event) => setScore(event.target.value)} /></div>
                <div className="space-y-1.5"><Label htmlFor="feedback-note">{copy.feedbackNote}</Label><textarea id="feedback-note" value={note} onChange={(event) => setNote(event.target.value)} className="min-h-24 w-full rounded-xl border border-input bg-background px-3 py-2 text-sm" /></div>
                <div className="flex gap-2"><Button type="submit">{copy.saveFeedback}</Button><Button type="button" variant="ghost" onClick={() => setCorrecting(false)}>{copy.cancel}</Button></div>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

function ListCard({ title, items, tone }: { title: string; items: string[]; tone: "success" | "warning" }) {
  const Icon = tone === "success" ? CheckCircle2 : TriangleAlert
  return <div className="rounded-3xl border border-border bg-card p-6 shadow-sm"><h2 className="text-xl font-semibold">{title}</h2><ul className="mt-5 space-y-4">{items.map((item) => <li key={item} className="flex gap-3 text-sm leading-6"><Icon className={`mt-1 size-4 shrink-0 ${tone === "success" ? "text-success" : "text-warning"}`} aria-hidden="true" /><span>{item}</span></li>)}</ul></div>
}
