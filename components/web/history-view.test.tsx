import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { webMessages } from "@/lib/i18n/web-messages"
import type { WebHistoryEntry } from "@/lib/web/types"
import { HistoryView } from "./history-view"

const entry: WebHistoryEntry = {
  id: "entry-1",
  userId: "user-1",
  profile: defaultProfile,
  job: detectedJob,
  analysis: goAnalysis,
  createdAt: "2026-08-25T12:00:00.000Z",
}

describe("HistoryView", () => {
  it("opens a completed analysis and can request history clearing", async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    const onClear = vi.fn()
    render(
      <HistoryView
        entries={[entry]}
        locale="en"
        copy={webMessages.en}
        onOpen={onOpen}
        onClear={onClear}
      />,
    )

    await user.click(
      screen.getByRole("button", { name: /Senior Python Backend Developer/ }),
    )
    expect(onOpen).toHaveBeenCalledWith(entry)
    await user.click(screen.getByRole("button", { name: "Clear history" }))
    expect(onClear).toHaveBeenCalledOnce()
  })

  it.each([
    { locale: "en" as const, label: "Task URL" },
    { locale: "ru" as const, label: "Ссылка на задачу" },
  ])("links to the original task in a separate protected tab in $locale", ({ locale, label }) => {
    const url = "https://www.freelancer.com/projects/n8n/task?ref=history#details"
    render(<HistoryView entries={[{ ...entry, job: { ...entry.job, url } }]} locale={locale} copy={webMessages[locale]} onOpen={vi.fn()} onClear={vi.fn()} />)
    const link = screen.getByRole("link", { name: label })
    expect(link).toHaveAttribute("href", url)
    expect(link).toHaveAttribute("target", "_blank")
    expect(link.getAttribute("rel")?.split(/\s+/)).toEqual(expect.arrayContaining(["noopener", "noreferrer"]))
  })

  it.each([undefined, "", "javascript:alert(1)", "data:text/html,task", "file:///task", "//example.com/task"])("keeps an entry with URL %s usable without an unsafe or empty link", async url => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    const saved = { ...entry, job: { ...entry.job, url } }
    render(<HistoryView entries={[saved]} locale="en" copy={webMessages.en} onOpen={onOpen} onClear={vi.fn()} />)
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /Senior Python Backend Developer/ }))
    expect(onOpen).toHaveBeenCalledWith(saved)
  })

  it.each([
    { locale: "en" as const, version: "Profile version: v2", changed: "Profile changed", action: "Reanalyze with current profile" },
    { locale: "ru" as const, version: "Версия профиля: v2", changed: "Профиль изменён", action: "Пересчитать по текущему профилю" },
  ])("marks only outdated analyses and offers a separate reanalysis action in $locale", async ({ locale, version, changed, action }) => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    const onReanalyze = vi.fn()
    const old = { ...entry, profileRevision: "2", profileChanged: true }
    const current = { ...entry, id: "current", job: { ...entry.job, title: "Current profile task" }, profileRevision: "3", profileChanged: false }
    render(<HistoryView entries={[old, current]} locale={locale} copy={webMessages[locale]} onOpen={onOpen} onClear={vi.fn()} onReanalyze={onReanalyze} />)

    expect(screen.getByText(version)).toBeVisible()
    expect(screen.getAllByText(changed)).toHaveLength(1)
    await user.click(screen.getByRole("button", { name: action }))
    expect(onReanalyze).toHaveBeenCalledWith(old)
    expect(onOpen).not.toHaveBeenCalled()
    expect(within(screen.getByRole("button", { name: /Current profile task/ })).queryByText(changed)).not.toBeInTheDocument()
  })

  it.each([
    { locale: "en" as const, unknown: "Profile version unavailable", changed: "Profile changed", action: "Reanalyze with current profile" },
    { locale: "ru" as const, unknown: "Версия профиля неизвестна", changed: "Профиль изменён", action: "Пересчитать по текущему профилю" },
  ])("keeps missing profile versions unknown without an outdated badge in $locale", ({ locale, unknown, changed, action }) => {
    render(<HistoryView entries={[{ ...entry, profileRevision: null, profileChanged: null }]} locale={locale} copy={webMessages[locale]} onOpen={vi.fn()} onClear={vi.fn()} onReanalyze={vi.fn()} />)
    expect(screen.getByText(unknown)).toBeVisible()
    expect(screen.queryByText(changed)).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: action })).not.toBeInTheDocument()
  })
})
