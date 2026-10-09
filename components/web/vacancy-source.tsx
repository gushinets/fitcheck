"use client"

import { useState } from "react"
import { FileText, Link2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { WebMessages } from "@/lib/i18n/web-messages"
import { WebApiError } from "@/lib/web/api"
import { vacancyDraftSchema } from "@/lib/web/schemas"
import type { VacancyDraft, VacancySourceMode } from "@/lib/web/types"

export function VacancySource({
  copy,
  initialDraft = null,
  onLoadUrl,
  onReview,
}: {
  copy: WebMessages
  initialDraft?: VacancyDraft | null
  onLoadUrl: (url: string) => Promise<VacancyDraft>
  onReview: (draft: VacancyDraft) => void
}) {
  const [mode, setMode] = useState<VacancySourceMode>(initialDraft?.sourceMode ?? "url")
  const [url, setUrl] = useState(initialDraft?.sourceUrl ?? "")
  const [title, setTitle] = useState(initialDraft?.sourceMode === "text" ? initialDraft.title : "")
  const [description, setDescription] = useState(initialDraft?.sourceMode === "text" ? initialDraft.description : "")
  const [skills, setSkills] = useState(initialDraft?.sourceMode === "text" ? initialDraft.skills.join(", ") : "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function loadUrl(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onReview(await onLoadUrl(url))
    } catch (reason) {
      setError(apiErrorMessage(reason, copy))
    } finally {
      setBusy(false)
    }
  }

  function reviewText(event: React.FormEvent) {
    event.preventDefault()
    const parsed = vacancyDraftSchema.safeParse({
      ...(initialDraft?.sourceMode === "text" ? initialDraft : {}),
      id: initialDraft?.id ?? crypto.randomUUID(),
      sourceMode: "text",
      title,
      description,
      skills: skills.split(",").map((skill) => skill.trim()).filter(Boolean),
      updatedAt: new Date().toISOString(),
    })
    if (parsed.success) onReview(parsed.data)
  }

  return (
    <section className="mx-auto max-w-4xl">
      <div className="text-center">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-primary">{copy.newAnalysis}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">{copy.chooseVacancyTitle}</h1>
        <p className="mx-auto mt-3 max-w-2xl text-muted-foreground">{copy.chooseVacancyDescription}</p>
      </div>
      <div className="mt-8 grid grid-cols-2 rounded-2xl border border-border bg-card p-1.5">
        {([
          { id: "url" as const, label: copy.fromUrl, icon: Link2 },
          { id: "text" as const, label: copy.pasteText, icon: FileText },
        ]).map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => { setMode(id); setError(null) }} className={`flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold ${mode === id ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-secondary"}`}>
            <Icon className="size-4" aria-hidden="true" />{label}
          </button>
        ))}
      </div>
      <div className="mt-4 rounded-3xl border border-border bg-card p-6 shadow-sm sm:p-8">
        {mode === "url" ? (
          <form onSubmit={loadUrl} className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="vacancy-url">{copy.vacancyUrl}</Label>
              <Input id="vacancy-url" type="url" required value={url} placeholder={copy.vacancyUrlPlaceholder} onChange={(event) => setUrl(event.target.value)} />
            </div>
            {error ? <div role="alert" className="rounded-xl bg-danger-muted p-4 text-sm text-danger">{error}</div> : null}
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button type="submit" disabled={busy || !url.trim()} className="h-11 sm:min-w-44">{busy ? copy.loadingVacancy : copy.loadVacancy}</Button>
              {error ? <Button type="button" variant="outline" onClick={() => setMode("text")}>{copy.pasteInstead}</Button> : null}
            </div>
          </form>
        ) : (
          <form onSubmit={reviewText} className="space-y-5">
            <div className="space-y-1.5"><Label htmlFor="manual-title">{copy.vacancyTitle}</Label><Input id="manual-title" required value={title} onChange={(event) => setTitle(event.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="manual-description">{copy.vacancyDescription}</Label><textarea id="manual-description" required value={description} onChange={(event) => setDescription(event.target.value)} className="min-h-56 w-full rounded-xl border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50" /></div>
            <div className="space-y-1.5"><Label htmlFor="manual-skills">{copy.vacancySkills}</Label><Input id="manual-skills" value={skills} onChange={(event) => setSkills(event.target.value)} /></div>
            <Button type="submit" disabled={!title.trim() || !description.trim()} className="h-11 sm:min-w-44">{copy.reviewVacancy}</Button>
          </form>
        )}
      </div>
    </section>
  )
}

function apiErrorMessage(error: unknown, copy: WebMessages) {
  if (!(error instanceof WebApiError)) return copy.fetchFailed
  const messages: Partial<Record<WebApiError["code"], string>> = {
    invalid_request: copy.invalidRequest,
    request_too_large: copy.requestTooLarge,
    blocked_address: copy.blockedAddress,
    redirect_limit: copy.redirectLimit,
    unsupported_content: copy.unsupportedContent,
    response_too_large: copy.responseTooLarge,
    timeout: copy.timeout,
    fetch_failed: copy.fetchFailed,
    extraction_insufficient: copy.extractionInsufficient,
    network_error: copy.networkError,
    invalid_response: copy.invalidResponse,
  }
  return messages[error.code] ?? copy.fetchFailed
}
