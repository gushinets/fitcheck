import { ChevronRight } from "lucide-react"
import type { HistoryEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

interface HistoryItemProps {
  entry: HistoryEntry
  onOpen: (entry: HistoryEntry) => void
}

export function HistoryItem({ entry, onOpen }: HistoryItemProps) {
  const isGo = entry.status === "GO"

  return (
    <button
      type="button"
      onClick={() => onOpen(entry)}
      className="flex w-full items-center gap-3 rounded-xl border border-border bg-card p-3 text-left transition-colors hover:bg-accent"
    >
      <span
        className={cn(
          "flex size-10 shrink-0 flex-col items-center justify-center rounded-lg text-sm font-bold tabular-nums",
          isGo
            ? "bg-success-muted text-success"
            : "bg-danger-muted text-danger",
        )}
      >
        {entry.score}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-semibold">
          {entry.jobTitle}
        </span>
        <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span
            className={cn(
              "font-semibold",
              isGo ? "text-success" : "text-danger",
            )}
          >
            {isGo ? "GO" : "NO-GO"}
          </span>
          <span aria-hidden="true">·</span>
          <span>{entry.timestamp}</span>
        </span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </button>
  )
}
