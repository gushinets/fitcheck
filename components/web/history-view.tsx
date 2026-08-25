"use client"

import { ArrowRight, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { WebMessages } from "@/lib/i18n/web-messages"
import type { Locale } from "@/lib/types"
import type { WebHistoryEntry } from "@/lib/web/types"

export function HistoryView({
  entries,
  locale,
  copy,
  onOpen,
  onClear,
}: {
  entries: WebHistoryEntry[]
  locale: Locale
  copy: WebMessages
  onOpen: (entry: WebHistoryEntry) => void
  onClear: () => void
}) {
  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-semibold uppercase tracking-[0.16em] text-primary">{copy.history}</p><h1 className="mt-3 text-3xl font-semibold tracking-tight">{copy.historyTitle}</h1><p className="mt-2 text-muted-foreground">{copy.historyDescription}</p></div>
        {entries.length ? <Button variant="outline" onClick={onClear}><Trash2 className="size-4" aria-hidden="true" />{copy.clearHistory}</Button> : null}
      </div>
      {!entries.length ? <div className="mt-8 rounded-3xl border border-dashed border-border bg-card p-12 text-center text-muted-foreground">{copy.noHistory}</div> : <div className="mt-8 grid gap-4 md:grid-cols-2">{entries.map((entry) => (
        <button key={entry.id} type="button" onClick={() => onOpen(entry)} className="group rounded-2xl border border-border bg-card p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md" aria-label={`${entry.job.title}, ${entry.analysis.score} ${copy.outOf100}`}>
          <div className="flex items-start justify-between gap-4"><div><h2 className="font-semibold">{entry.job.title}</h2><p className="mt-1 text-xs text-muted-foreground">{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(entry.createdAt))}</p></div><div className={`rounded-xl px-3 py-2 text-lg font-bold ${entry.analysis.status === "GO" ? "bg-success-muted text-success" : "bg-warning-muted text-warning-foreground"}`}>{entry.analysis.score}</div></div>
          <p className="mt-4 line-clamp-2 text-sm leading-6 text-muted-foreground">{entry.analysis.summary}</p><span className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary">{entry.analysis.status === "GO" ? copy.go : copy.noGo}<ArrowRight className="size-4 transition group-hover:translate-x-1" aria-hidden="true" /></span>
        </button>
      ))}</div>}
    </section>
  )
}
