"use client"

import { cn } from "@/lib/utils"

export type DemoScenario =
  | "onboarding"
  | "go"
  | "nogo"
  | "unsupported"
  | "error"

const scenarios: { key: DemoScenario; label: string }[] = [
  { key: "onboarding", label: "First run" },
  { key: "go", label: "GO result" },
  { key: "nogo", label: "NO-GO result" },
  { key: "unsupported", label: "Unsupported" },
  { key: "error", label: "Error" },
]

interface DemoControlsProps {
  active: DemoScenario
  onSelect: (scenario: DemoScenario) => void
}

export function DemoControls({ active, onSelect }: DemoControlsProps) {
  return (
    <div className="w-full max-w-[420px]">
      <p className="mb-2 text-center text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        Preview states
      </p>
      <div className="flex flex-wrap justify-center gap-1.5">
        {scenarios.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => onSelect(key)}
            aria-pressed={active === key}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              active === key
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
