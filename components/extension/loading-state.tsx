"use client"

import { useEffect, useState } from "react"
import { Check, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { messages, type Messages } from "@/lib/i18n/messages"

const LOADING_STEP_COUNT = 4

export function LoadingState({ copy = messages.en }: { copy?: Messages }) {
  const [step, setStep] = useState(0)
  const loadingSteps = [copy.readingRequirements, copy.comparingSkills, copy.checkingRate, copy.evaluatingRisks]

  useEffect(() => {
    const timer = setTimeout(
      () => setStep((current) => (current + 1) % (LOADING_STEP_COUNT + 1)),
      700,
    )
    return () => clearTimeout(timer)
  }, [step])

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-6 py-10">
      <div className="relative mb-5 flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Loader2 className="size-6 animate-spin" aria-hidden="true" />
      </div>
      <h2 className="text-[15px] font-semibold">{copy.analyzing}</h2>
      <p className="mt-1 text-center text-xs text-muted-foreground">
        Comparing this job with your profile.
      </p>

      <ul className="mt-6 w-full max-w-[260px] space-y-2.5" aria-live="polite">
        {loadingSteps.map((label, i) => {
          const isDone = i < step
          const isActive = i === step
          return (
            <li
              key={label}
              className={cn(
                "flex items-center gap-2.5 text-[13px] transition-colors",
                isDone
                  ? "text-foreground"
                  : isActive
                    ? "text-foreground"
                    : "text-muted-foreground/60",
              )}
            >
              <span
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded-full border",
                  isDone
                    ? "border-success bg-success text-success-foreground"
                    : isActive
                      ? "border-primary text-primary"
                      : "border-border",
                )}
              >
                {isDone ? (
                  <Check className="size-3" strokeWidth={3} aria-hidden="true" />
                ) : isActive ? (
                  <Loader2 className="size-3 animate-spin" aria-hidden="true" />
                ) : null}
              </span>
              {label}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
