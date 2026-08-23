import type { FitStatus } from "@/lib/types"
import { cn } from "@/lib/utils"
import { messages, type Messages } from "@/lib/i18n/messages"

interface FitScoreProps {
  score: number
  status: FitStatus
  size?: number
  copy?: Messages
}

/**
 * Circular score ring. The score is the dominant visual element on the
 * result screen, so it is intentionally large and high-contrast.
 */
export function FitScore({ score, status, size = 132, copy = messages.en }: FitScoreProps) {
  const stroke = 10
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, score))
  const dash = (clamped / 100) * circumference
  const ringColor = status === "GO" ? "var(--success)" : "var(--danger)"

  return (
    <div
      className="relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Fit score ${score} out of 100`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--muted)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={ringColor}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          className="transition-[stroke-dasharray] duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className={cn(
            "text-4xl font-bold leading-none tracking-tight tabular-nums",
            status === "GO" ? "text-success" : "text-danger",
          )}
        >
          {score}
        </span>
        <span className="mt-1 text-[11px] font-medium text-muted-foreground">
          {copy.outOf100}
        </span>
      </div>
    </div>
  )
}
