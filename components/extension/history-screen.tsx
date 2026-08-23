"use client"

import { HistoryItem } from "./history-item"
import { EmptyState } from "./empty-state"
import type { HistoryEntry } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"

interface HistoryScreenProps {
  entries: HistoryEntry[]
  onOpen: (entry: HistoryEntry) => void
  onClear?: () => void
  copy?: Messages
}

export function HistoryScreen({ entries, onOpen, onClear, copy = messages.en }: HistoryScreenProps) {
  if (!entries.length) {
    return (
      <EmptyState
        title={copy.noAnalyses}
        description={copy.noAnalysesDescription}
      />
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto px-4 py-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold text-muted-foreground">{copy.recentAnalyses}</h2>
        {onClear ? <button type="button" onClick={onClear} className="text-xs text-danger">{copy.clearHistory}</button> : null}
      </div>
      <ul className="flex flex-col gap-2">
        {entries.map((entry) => (
          <li key={entry.id}>
            <HistoryItem entry={entry} onOpen={onOpen} />
          </li>
        ))}
      </ul>
    </div>
  )
}
