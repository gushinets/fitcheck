import { Clock } from "lucide-react"
import type { Job } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"
import { formatMoney, formatRateRange } from "@/lib/currency"

interface JobSummaryProps {
  job: Job
  compact?: boolean
  copy?: Messages
}

function formatRate(job: Job, copy: Messages) {
  if (job.hourlyRateMin !== undefined || job.hourlyRateMax !== undefined) {
    return `${formatMoney(formatRateRange(job.hourlyRateMin, job.hourlyRateMax), job.budgetCurrency)}/hr`
  }
  return copy.rateNotListed
}

export function JobSummary({ job, compact = false, copy = messages.en }: JobSummaryProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-3.5">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <span className="inline-block size-1.5 rounded-full bg-success" aria-hidden="true" />
        {copy.detectedOnUpwork}
      </div>
      <h2 className="text-pretty text-[15px] font-semibold leading-snug">
        {job.title}
      </h2>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{formatRate(job, copy)}</span>
        {job.experienceLevel ? <span>{job.experienceLevel}</span> : null}
        {job.postedAgo ? (
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" aria-hidden="true" />
            {job.postedAgo.replace("Posted ", "")}
          </span>
        ) : null}
      </div>
      {!compact ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {job.skills.map((skill) => (
            <span
              key={skill}
              className="rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
            >
              {skill}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
