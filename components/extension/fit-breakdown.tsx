import type { FitBreakdown as Breakdown } from "@/lib/types"
import { breakdownLabels } from "@/lib/mock-data"
import { cn } from "@/lib/utils"

function barColor(value: number) {
  if (value >= 75) return "bg-success"
  if (value >= 55) return "bg-warning"
  return "bg-danger"
}

interface FitBreakdownProps {
  breakdown: Breakdown
}

export function FitBreakdown({ breakdown }: FitBreakdownProps) {
  const rows = Object.entries(breakdown) as [keyof Breakdown, number][]

  return (
    <ul className="flex flex-col gap-3">
      {rows.map(([key, value]) => (
        <li key={key} className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-[13px]">
            <span className="font-medium text-foreground">
              {breakdownLabels[key]}
            </span>
            <span className="font-semibold tabular-nums text-foreground">
              {value}
              <span className="text-muted-foreground"> / 100</span>
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full transition-all", barColor(value))}
              style={{ width: `${value}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  )
}
