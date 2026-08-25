"use client"

import { useState } from "react"
import { ArrowLeft, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { WebMessages } from "@/lib/i18n/web-messages"
import { vacancyDraftSchema } from "@/lib/web/schemas"
import type { VacancyDraft } from "@/lib/web/types"

export function VacancyReview({
  draft,
  copy,
  onBack,
  onAnalyze,
}: {
  draft: VacancyDraft
  copy: WebMessages
  onBack: (draft: VacancyDraft) => void
  onAnalyze: (draft: VacancyDraft) => void
}) {
  const [title, setTitle] = useState(draft.title)
  const [description, setDescription] = useState(draft.description)
  const [skills, setSkills] = useState(draft.skills.join(", "))
  const [rateMin, setRateMin] = useState(draft.hourlyRateMin?.toString() ?? "")
  const [rateMax, setRateMax] = useState(draft.hourlyRateMax?.toString() ?? "")
  const [fixedBudget, setFixedBudget] = useState(draft.fixedBudget?.toString() ?? "")

  function currentDraft() {
    return vacancyDraftSchema.parse({
      ...draft,
      title,
      description,
      skills: skills.split(",").map((skill) => skill.trim()).filter(Boolean),
      hourlyRateMin: rateMin ? Number(rateMin) : undefined,
      hourlyRateMax: rateMax ? Number(rateMax) : undefined,
      fixedBudget: fixedBudget ? Number(fixedBudget) : undefined,
      updatedAt: new Date().toISOString(),
    })
  }

  return (
    <section className="mx-auto max-w-4xl rounded-3xl border border-border bg-card p-6 shadow-sm sm:p-10">
      <button type="button" onClick={() => onBack(currentDraft())} className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline">
        <ArrowLeft className="size-4" aria-hidden="true" />{copy.backToSelection}
      </button>
      <h1 className="mt-6 text-3xl font-semibold tracking-tight">{copy.reviewTitle}</h1>
      <p className="mt-2 text-muted-foreground">{copy.reviewDescription}</p>
      <form onSubmit={(event) => { event.preventDefault(); onAnalyze(currentDraft()) }} className="mt-8 space-y-5">
        <div className="space-y-1.5"><Label htmlFor="review-title">{copy.vacancyTitle}</Label><Input id="review-title" value={title} onChange={(event) => setTitle(event.target.value)} /></div>
        <div className="space-y-1.5"><Label htmlFor="review-description">{copy.vacancyDescription}</Label><textarea id="review-description" value={description} onChange={(event) => setDescription(event.target.value)} className="min-h-64 w-full rounded-xl border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50" /></div>
        <div className="space-y-1.5"><Label htmlFor="review-skills">{copy.vacancySkills}</Label><Input id="review-skills" value={skills} onChange={(event) => setSkills(event.target.value)} /></div>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-1.5"><Label htmlFor="review-rate-min">{copy.hourlyRateMin}</Label><Input id="review-rate-min" type="number" min={0} value={rateMin} onChange={(event) => setRateMin(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="review-rate-max">{copy.hourlyRateMax}</Label><Input id="review-rate-max" type="number" min={0} value={rateMax} onChange={(event) => setRateMax(event.target.value)} /></div>
          <div className="space-y-1.5"><Label htmlFor="review-budget">{copy.fixedBudget}</Label><Input id="review-budget" type="number" min={0} value={fixedBudget} onChange={(event) => setFixedBudget(event.target.value)} /></div>
        </div>
        <Button type="submit" disabled={!title.trim() || !description.trim()} className="h-12 w-full text-base font-semibold sm:w-auto sm:min-w-56"><Sparkles className="size-4" aria-hidden="true" />{copy.analyzeVacancy}</Button>
      </form>
    </section>
  )
}
