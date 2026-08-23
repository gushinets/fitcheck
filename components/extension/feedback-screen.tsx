"use client"

import { useState } from "react"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { Messages } from "@/lib/i18n/messages"
import type { FitAnalysis } from "@/lib/types"

interface FeedbackScreenProps {
  analysis: FitAnalysis
  copy: Messages
  onSave: (feedback: { correctedScore: number; note?: string }) => void
  onCancel: () => void
}

export function FeedbackScreen({ analysis, copy, onSave, onCancel }: FeedbackScreenProps) {
  const [score, setScore] = useState(String(analysis.score))
  const [note, setNote] = useState("")

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const correctedScore = Math.min(100, Math.max(0, Number(score)))
    const trimmedNote = note.trim()
    onSave({ correctedScore, ...(trimmedNote ? { note: trimmedNote } : {}) })
  }

  return (
    <form onSubmit={submit} className="flex flex-1 flex-col overflow-y-auto px-4 py-4">
      <button type="button" onClick={onCancel} className="mb-4 flex items-center gap-1 text-xs text-muted-foreground">
        <ArrowLeft className="size-4" aria-hidden="true" />
        {copy.cancel}
      </button>
      <h2 className="text-lg font-semibold">{copy.feedbackTitle}</h2>
      <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{copy.feedbackDescription}</p>
      <div className="mt-6 flex flex-col gap-1.5">
        <Label htmlFor="corrected-score">{copy.correctScore}</Label>
        <Input id="corrected-score" type="number" min={0} max={100} required value={score} onChange={(event) => setScore(event.target.value)} />
      </div>
      <div className="mt-4 flex flex-col gap-1.5">
        <Label htmlFor="feedback-note">{copy.feedbackNote}</Label>
        <textarea id="feedback-note" maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} placeholder={copy.feedbackPlaceholder} className="min-h-28 rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      </div>
      <Button type="submit" className="mt-auto h-11 w-full">{copy.saveFeedback}</Button>
    </form>
  )
}
