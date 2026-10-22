import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { webMessages } from "@/lib/i18n/web-messages"
import type { WebHistoryEntry } from "@/lib/web/types"
import { AnalysisResult } from "./analysis-result"

const entry: WebHistoryEntry = {
  id: "entry-1",
  userId: "user-1",
  profile: defaultProfile,
  job: detectedJob,
  analysis: goAnalysis,
  createdAt: "2026-08-25T12:00:00.000Z",
}

describe("AnalysisResult", () => {
  it.each([
    ["en", "Suitable if the client agrees to communicate in English", "Fit condition"],
    ["ru", "Подходит, если клиент согласится общаться на английском", "Условие соответствия"],
  ] as const)("shows the saved %s fit condition with the GO verdict", (locale, fitCondition, label) => {
    const analysis = { ...entry.analysis, fitCondition }
    render(<AnalysisResult entry={{ ...entry, analysis }} copy={webMessages[locale]} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.getByRole("note", { name: label })).toHaveTextContent(fitCondition)
    expect(screen.getByRole("note", { name: label })).toBeVisible()
    expect(screen.getByText(webMessages[locale].go)).toBeVisible()
  })

  it.each([
    { fitCondition: undefined }, { fitCondition: null }, { fitCondition: "   " },
    { fitCondition: "Suitable if scope is confirmed", status: "NO_GO" as const, score: 60 },
    { fitCondition: "Suitable if scope is confirmed", risks: [] },
  ])("omits inapplicable conditions for unconditional, legacy or NO-GO results", changes => {
    const analysis = { ...entry.analysis, ...changes }
    render(<AnalysisResult entry={{ ...entry, analysis }} copy={webMessages.en} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.queryByRole("note", { name: "Fit condition" })).not.toBeInTheDocument()
  })

  it.each([
    ["en", 69, "NO_GO", "Score is below the threshold."],
    ["en", 70, "GO", "Score meets the threshold."],
    ["en", 71, "GO", "Score meets the threshold."],
    ["ru", 69, "NO_GO", "Оценка ниже порога."],
    ["ru", 70, "GO", "Оценка достигла порога."],
    ["ru", 71, "GO", "Оценка достигла порога."],
  ] as const)("explains the %s score %s against the saved verdict threshold", (locale, score, status, explanation) => {
    const analysis = { ...entry.analysis, score, status, verdictThreshold: 70 }
    render(<AnalysisResult entry={{ ...entry, analysis }} copy={webMessages[locale]} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    const scoreGroup = within(screen.getByRole("group", { name: webMessages[locale].fitScore }))
    expect(scoreGroup.getByText(locale === "ru" ? "Порог «ПОДХОДИТ»: 70 / 100" : "GO threshold: 70 / 100")).toBeVisible()
    expect(scoreGroup.getByText(explanation)).toBeVisible()
    expect(screen.getByText(status === "GO" ? webMessages[locale].go : webMessages[locale].noGo)).toBeVisible()
  })

  it.each([[79, 80, "NO_GO"], [0, 0, "GO"], [99, 100, "NO_GO"]] as const)("uses the supplied threshold %s / %s without a hardcoded default", (score, threshold, status) => {
    const analysis = { ...entry.analysis, score, status, verdictThreshold: threshold }
    render(<AnalysisResult entry={{ ...entry, analysis }} copy={webMessages.en} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.getByText(`GO threshold: ${threshold} / 100`)).toBeVisible()
    expect(screen.getByText(score >= threshold ? "Score meets the threshold." : "Score is below the threshold.")).toBeVisible()
  })

  it.each(["en", "ru"] as const)("does not invent a threshold for legacy %s results", locale => {
    render(<AnalysisResult entry={entry} copy={webMessages[locale]} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.getByText(locale === "ru" ? "Порог вердикта не указан." : "Verdict threshold unavailable.")).toBeVisible()
    expect(screen.queryByText(/70 \/ 100/)).not.toBeInTheDocument()
  })

  it("explains when no confirmed strengths were found", () => {
    render(<AnalysisResult entry={{ ...entry, analysis: { ...entry.analysis, strengths: [] } }} copy={webMessages.ru} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.getByText("Подтверждённые сильные стороны не найдены.")).toBeVisible()
  })
  it("displays an upper-only fixed budget after review", () => {
    render(<AnalysisResult entry={{ ...entry, job: { ...entry.job, fixedBudgetMax: 750, budgetCurrency: "EUR" } }} copy={webMessages.en} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.getByText("≤750 EUR")).toBeVisible()
  })
  it("displays the full fixed budget range", () => {
    render(<AnalysisResult entry={{ ...entry, job: { ...entry.job, fixedBudget: 250, fixedBudgetMax: 750, budgetCurrency: "EUR" } }} copy={webMessages.en} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.getByText("250–750 EUR")).toBeVisible()
  })
  it("shows stored currencies and a conversion notice in the Russian report", () => {
    render(<AnalysisResult entry={{ ...entry,
      profile: { ...entry.profile!, preferredRate: 25, rateCurrency: "USD" },
      job: { ...entry.job, hourlyRateMin: 25, hourlyRateMax: 50, budgetCurrency: "EUR" },
    }} copy={webMessages.ru} onBack={vi.fn()} onAnalyzeAnother={vi.fn()} onSaveFeedback={vi.fn()} />)
    expect(screen.getByText("25 USD/час")).toBeVisible()
    expect(screen.getByText("25–50 EUR/час")).toBeVisible()
    expect(screen.getByText(/Валюты различаются/)).toBeVisible()
  })
  it("shows the complete fit decision and breakdown", () => {
    render(
      <AnalysisResult
        entry={entry}
        copy={webMessages.en}
        onBack={vi.fn()}
        onAnalyzeAnother={vi.fn()}
        onSaveFeedback={vi.fn()}
      />,
    )

    expect(screen.getByLabelText("Fit score 82 out of 100")).toBeVisible()
    expect(screen.getByText("Strong Python and Django match")).toBeVisible()
    expect(screen.getByText("AWS experience is preferred but missing from your profile")).toBeVisible()
    expect(screen.getByText("88")).toBeVisible()
    expect(screen.getByText("95")).toBeVisible()
  })

  it("saves a correction without replacing the original score", async () => {
    const user = userEvent.setup()
    const onSaveFeedback = vi.fn()
    render(
      <AnalysisResult
        entry={{ ...entry, analysis: { ...entry.analysis, verdictThreshold: 80, fitCondition: "Suitable if you can cover the client's US working hours" } }}
        copy={webMessages.en}
        onBack={vi.fn()}
        onAnalyzeAnother={vi.fn()}
        onSaveFeedback={onSaveFeedback}
      />,
    )

    await user.click(screen.getByRole("button", { name: "Correct the score" }))
    await user.clear(screen.getByLabelText("Correct score"))
    await user.type(screen.getByLabelText("Correct score"), "74")
    await user.type(screen.getByLabelText("What did the analysis miss?"), "Timezone overlap matters")
    await user.click(screen.getByRole("button", { name: "Save correction" }))

    expect(onSaveFeedback).toHaveBeenCalledWith({
      correctedScore: 74,
      note: "Timezone overlap matters",
    })
    expect(screen.getByLabelText("Fit score 82 out of 100")).toBeVisible()
    expect(screen.getByText("GO threshold: 80 / 100")).toBeVisible()
    expect(screen.getByText("Score meets the threshold.")).toBeVisible()
    expect(screen.getByRole("note", { name: "Fit condition" })).toHaveTextContent("Suitable if you can cover the client's US working hours")
  })
})
