"use client"

import { ArrowRight, ExternalLink, SkipForward } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FitScore } from "./fit-score"
import { FitStatus } from "./fit-status"
import { StrengthItem } from "./strength-item"
import { RiskItem } from "./risk-item"
import type { FitAnalysis, Job } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"

interface ResultScreenProps {
  job: Job
  analysis: FitAnalysis
  onViewDetails: () => void
  onInaccurate: () => void
  onApply?: () => void
  onSkip?: () => void
  copy?: Messages
}

export function ResultScreen({
  job,
  analysis,
  onViewDetails,
  onInaccurate,
  onApply,
  onSkip,
  copy = messages.en,
}: ResultScreenProps) {
  const isGo = analysis.status === "GO"

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      <div className="flex flex-col gap-4 px-4 py-4">
        {/* Decision block — the first and most dominant thing on screen */}
        <section className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-card px-4 py-5">
          <p className="truncate text-center text-[13px] font-medium text-muted-foreground">
            {job.title}
          </p>
          <FitScore score={analysis.score} status={analysis.status} copy={copy} />
          <FitStatus status={analysis.status} label={analysis.label} />
          <p className="max-w-[320px] text-balance text-center text-[13px] leading-relaxed text-muted-foreground">
            {analysis.summary}
          </p>
        </section>

        {/* Strengths */}
        <section>
          <h3 className="mb-2 text-[13px] font-semibold text-foreground">
            {copy.strengths}
          </h3>
          <ul className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3">
            {analysis.strengths.length === 0 && <li className="text-[13px] text-muted-foreground">{copy.noConfirmedStrengths}</li>}
            {analysis.strengths.map((s) => (
              <StrengthItem key={s} text={s} />
            ))}
          </ul>
        </section>

        {/* Risks */}
        <section>
          <h3 className="mb-2 text-[13px] font-semibold text-foreground">{copy.risks}</h3>
          <ul className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3">
            {analysis.risks.map((r) => (
              <RiskItem key={r} text={r} />
            ))}
          </ul>
        </section>
      </div>

      {/* Sticky action bar keeps the primary decision reachable */}
      <div className="sticky bottom-0 mt-auto flex flex-col gap-2 border-t border-border bg-card/95 px-4 py-3 backdrop-blur">
        {isGo ? (
          <Button onClick={onApply} className="h-11 w-full text-sm font-semibold">
            <ExternalLink className="size-4" aria-hidden="true" />
            {copy.apply}
          </Button>
        ) : (
          <Button
            variant="secondary"
            onClick={onSkip}
            className="h-11 w-full text-sm font-semibold"
          >
            <SkipForward className="size-4" aria-hidden="true" />
            {copy.skip}
          </Button>
        )}
        <div className="flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={onViewDetails}
            className="text-primary"
          >
            {copy.viewDetails}
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Button>
          <button
            type="button"
            onClick={onInaccurate}
            className="text-[11px] text-muted-foreground underline-offset-4 hover:underline"
          >
            {copy.notAccurate}
          </button>
        </div>
      </div>
    </div>
  )
}
