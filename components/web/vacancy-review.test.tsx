import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { webMessages } from "@/lib/i18n/web-messages"
import type { VacancyDraft } from "@/lib/web/types"
import { VacancyReview } from "./vacancy-review"
import userEvent from "@testing-library/user-event"

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
  it("lets the user correct both ends of an extracted fixed budget range", async () => {
    const onAnalyze = vi.fn()
    render(<VacancyReview draft={{ ...draft, fixedBudget: 250, fixedBudgetMax: 750, budgetCurrency: "EUR" }} copy={webMessages.en} onBack={vi.fn()} onAnalyze={onAnalyze} />)
    const user = userEvent.setup()
    expect(screen.getByLabelText("Fixed budget to")).toHaveValue(750)
    await user.clear(screen.getByLabelText("Fixed budget to"))
    await user.type(screen.getByLabelText("Fixed budget to"), "900.5")
    await user.click(screen.getByRole("button", { name: "Analyze task" }))
    expect(onAnalyze).toHaveBeenCalledWith(expect.objectContaining({ fixedBudget: 250, fixedBudgetMax: 900.5, budgetCurrency: "EUR" }))
  })
  it.each([
    ["en" as const, "EUR/hour"],
    ["ru" as const, "EUR/час"],
  ])("shows explicit task currency in %s", (locale, hourlyCurrency) => {
    render(
      <VacancyReview
        draft={{ ...draft, budgetCurrency: "EUR" }}
        copy={webMessages[locale]}
        onBack={vi.fn()}
        onAnalyze={vi.fn()}
      />,
    )

    expect(screen.getAllByText(hourlyCurrency)).toHaveLength(2)
    expect(screen.getByRole("combobox")).toHaveValue("EUR")
  })

  it("saves a selected budget currency without changing amounts", async () => {
    const onAnalyze = vi.fn()
    render(<VacancyReview draft={draft} copy={webMessages.en} onBack={vi.fn()} onAnalyze={onAnalyze} />)
    const user = userEvent.setup()
    await user.selectOptions(screen.getByRole("combobox", { name: "Task budget currency" }), "RUB")
    await user.click(screen.getByRole("button", { name: "Analyze task" }))
    expect(onAnalyze).toHaveBeenCalledWith(expect.objectContaining({ fixedBudget: 80000, budgetCurrency: "RUB" }))
  })
})
