"use client"

import { JobSummary } from "./job-summary"
import { AnalyzeButton } from "./analyze-button"
import type { FreelancerProfile, Job } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"
import { formatMoney } from "@/lib/currency"

interface ReadyScreenProps {
  job: Job
  profile: FreelancerProfile
  onAnalyze: () => void
  copy?: Messages
}

export function ReadyScreen({ job, profile, onAnalyze, copy = messages.en }: ReadyScreenProps) {
  return (
    <div className="flex flex-1 flex-col overflow-y-auto px-4 py-4">
      <div className="flex flex-1 flex-col gap-4">
        <JobSummary job={job} copy={copy} />

        <div className="rounded-xl border border-border bg-card p-3.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {copy.comparingAgainst}
            </span>
          </div>
          <p className="mt-1 text-[13px] font-semibold">{profile.specialization}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {profile.experienceYears} yrs · {formatMoney(profile.preferredRate, profile.rateCurrency)}/hr ·{" "}
            {profile.englishLevel}
          </p>
        </div>
      </div>

      <div className="mt-4">
        <AnalyzeButton onClick={onAnalyze} copy={copy} />
      </div>
    </div>
  )
}
