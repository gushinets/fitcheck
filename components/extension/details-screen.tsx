"use client"

import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FitBreakdown } from "./fit-breakdown"
import type { FitAnalysis, Job } from "@/lib/types"
import { cn } from "@/lib/utils"
import { messages, type Messages } from "@/lib/i18n/messages"

interface DetailsScreenProps {
  job: Job
  analysis: FitAnalysis
  onBack: () => void
  copy?: Messages
}

export function DetailsScreen({ job, analysis, onBack, copy = messages.en }: DetailsScreenProps) {
  const isGo = analysis.status === "GO"

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onBack}
          aria-label={copy.back}
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
        </Button>
        <span className="text-[13px] font-semibold">{copy.fitBreakdown}</span>
        <span
          className={cn(
            "ml-auto rounded-full px-2 py-0.5 text-xs font-bold tabular-nums",
            isGo ? "bg-success-muted text-success" : "bg-danger-muted text-danger",
          )}
        >
          {analysis.score} · {isGo ? "GO" : "NO-GO"}
        </span>
      </div>

      <div className="flex flex-col gap-4 px-4 py-4">
        <p className="truncate text-[13px] font-medium text-muted-foreground">
          {job.title}
        </p>

        <div className="rounded-xl border border-border bg-card p-3.5">
          <FitBreakdown breakdown={analysis.breakdown} />
        </div>

        <div className="rounded-xl border-l-2 border-l-warning bg-warning-muted/50 p-3">
          <p className="text-[13px] leading-relaxed text-foreground">
            {analysis.summary}
          </p>
        </div>

        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {copy.scoreDisclaimer}
        </p>
      </div>
    </div>
  )
}
