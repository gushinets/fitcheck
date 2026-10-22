"use client"

import { ArrowRight, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { WebMessages } from "@/lib/i18n/web-messages"
import type { Locale } from "@/lib/types"
import type { HistoryFilters, WebHistoryEntry } from "@/lib/web/types"

export function HistoryView({
  entries,
  locale,
  copy,
  onOpen,
  onClear,
  onMore,
  onStatus,
  onFilter,
  onReanalyze,
  filters = { applicationStatus: "", verdict: "" },
  busy = false,
}: {
  entries: WebHistoryEntry[]
  locale: Locale
  copy: WebMessages
  onOpen: (entry: WebHistoryEntry) => void
  onClear: () => void
  onMore?: () => void
  onStatus?: (entry: WebHistoryEntry, status: NonNullable<WebHistoryEntry["applicationStatus"]>) => void
  onFilter?: (filters: HistoryFilters) => void
  onReanalyze?: (entry: WebHistoryEntry) => void
  filters?: HistoryFilters
  busy?: boolean
}) {
  const filtered = Boolean(filters.applicationStatus || filters.verdict)
  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-semibold uppercase tracking-[0.16em] text-primary">{copy.history}</p><h1 className="mt-3 text-3xl font-semibold tracking-tight">{copy.historyTitle}</h1><p className="mt-2 text-muted-foreground">{copy.historyDescription}</p></div>
        {entries.length ? <Button variant="outline" disabled={busy} onClick={onClear}><Trash2 className="size-4" aria-hidden="true" />{copy.clearHistory}</Button> : null}
      </div>
      {onFilter ? <div className="mt-4 flex flex-wrap items-center gap-3">
        <select disabled={busy} aria-label={copy.historyVerdictFilter} className="max-w-full rounded-lg border p-2" value={filters.verdict} onChange={event => onFilter({ ...filters, verdict: event.target.value as HistoryFilters["verdict"] })}><option value="">{copy.historyAllVerdicts}</option><option value="GO">{copy.go}</option><option value="NO_GO">{copy.noGo}</option></select>
        <select disabled={busy} aria-label={locale === "ru" ? "Фильтр по статусу отклика" : "Filter application status"} className="max-w-full rounded-lg border p-2" value={filters.applicationStatus} onChange={event => onFilter({ ...filters, applicationStatus: event.target.value as HistoryFilters["applicationStatus"] })}><option value="">{locale === "ru" ? "Все статусы" : "All statuses"}</option>{applicationStatuses.map(status => <option key={status} value={status}>{statusLabel(status, locale)}</option>)}</select>
        {filtered ? <Button variant="outline" disabled={busy} onClick={() => onFilter({ applicationStatus: "", verdict: "" })}>{copy.historyResetFilters}</Button> : null}
      </div> : null}
      {busy ? <p role="status" className="mt-3 text-sm text-muted-foreground">{copy.loading}</p> : null}
      {!entries.length ? <div className="mt-8 rounded-3xl border border-dashed border-border bg-card p-12 text-center text-muted-foreground">{filtered ? copy.historyNoMatches : copy.noHistory}</div> : <div className="mt-8 grid gap-4 md:grid-cols-2">{entries.map((entry) => (
        <div key={entry.id} className="rounded-2xl border border-border bg-card">
        <button key={entry.id} type="button" onClick={() => onOpen(entry)} className="group rounded-2xl border border-border bg-card p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md" aria-label={`${entry.job.title}, ${entry.analysis.score} ${copy.outOf100}`}>
          <div className="flex items-start justify-between gap-4"><div><h2 className="font-semibold">{entry.job.title}</h2><p className="mt-1 text-xs text-muted-foreground">{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(entry.createdAt))}</p></div><div className={`rounded-xl px-3 py-2 text-lg font-bold ${entry.analysis.status === "GO" ? "bg-success-muted text-success" : "bg-warning-muted text-warning-foreground"}`}>{entry.analysis.score}</div></div>
          <p className="mt-4 line-clamp-2 text-sm leading-6 text-muted-foreground">{entry.analysis.summary}</p><span className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary">{entry.analysis.status === "GO" ? copy.go : copy.noGo}<ArrowRight className="size-4 transition group-hover:translate-x-1" aria-hidden="true" /></span>
        </button>
        {entry.job.url && /^https?:\/\//i.test(entry.job.url) ? <a className="mx-5 block text-sm text-primary underline" href={entry.job.url} target="_blank" rel="noopener noreferrer">{copy.vacancyUrl}</a> : null}
        <div className="mx-5 my-3 space-y-2">
          <p className="text-sm text-muted-foreground">{entry.profileRevision ? `${copy.profileVersion}: v${entry.profileRevision}` : copy.profileVersionUnknown}</p>
          {entry.profileChanged === true ? <>
            <p className="w-fit rounded-lg bg-warning-muted px-2 py-1 text-sm text-warning-foreground">{copy.profileChanged}</p>
            {onReanalyze ? <Button type="button" variant="outline" className="h-auto min-h-9 max-w-full whitespace-normal py-2 text-left" onClick={() => onReanalyze(entry)}>{copy.reanalyzeCurrentProfile}</Button> : null}
          </> : null}
        </div>
        {onStatus ? <select disabled={busy} className="m-5 max-w-[calc(100%-2.5rem)] rounded-lg border p-2" aria-label={`${locale === "ru" ? "Статус отклика" : "Application status"}: ${entry.job.title}`} value={entry.applicationStatus ?? "not_applied"} onChange={event => onStatus(entry, event.target.value as NonNullable<WebHistoryEntry["applicationStatus"]>)}>{applicationStatuses.map(status => <option key={status} value={status}>{statusLabel(status, locale)}</option>)}</select> : null}
        </div>
      ))}</div>}
      {onMore ? <Button className="mt-5" variant="outline" disabled={busy} onClick={onMore}>{locale === "ru" ? "Загрузить ещё" : "Load more"}</Button> : null}
    </section>
  )
}

const applicationStatuses = ["not_applied", "applied", "replied", "interview", "rejected", "hired"] as const
function statusLabel(status: typeof applicationStatuses[number], locale: Locale) {
  const labels = { not_applied: ["Not applied", "Не откликался"], applied: ["Applied", "Откликнулся"], replied: ["Replied", "Получен ответ"], interview: ["Interview", "Собеседование"], rejected: ["Rejected", "Отказ"], hired: ["Hired", "Принят"] }
  return labels[status][locale === "ru" ? 1 : 0]
}
