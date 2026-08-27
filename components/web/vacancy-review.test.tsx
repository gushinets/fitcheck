import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { webMessages } from "@/lib/i18n/web-messages"
import type { VacancyDraft } from "@/lib/web/types"
import { VacancyReview } from "./vacancy-review"

const draft: VacancyDraft = {
  id: "draft-1",
  sourceMode: "text",
  title: "Backend-разработчик",
  description: "Разработка и поддержка внутренних сервисов.",
  skills: ["Python"],
  fixedBudget: 80_000,
  updatedAt: "2026-08-27T19:00:00.000Z",
}

describe("VacancyReview", () => {
  it.each([
    ["en" as const, "$/hour", "$"],
    ["ru" as const, "₽/час", "₽"],
  ])("shows %s vacancy money inputs with their locale currency", (locale, hourlyCurrency, fixedCurrency) => {
    render(
      <VacancyReview
        draft={draft}
        copy={webMessages[locale]}
        onBack={vi.fn()}
        onAnalyze={vi.fn()}
      />,
    )

    expect(screen.getAllByText(hourlyCurrency)).toHaveLength(2)
    expect(screen.getByText(fixedCurrency)).toBeVisible()
  })
})
