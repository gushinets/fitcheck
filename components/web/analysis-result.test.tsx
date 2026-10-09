import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
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
  it("shows stored currencies and a conversion notice in the Russian report", () => {
    render(<AnalysisResult entry={{ ...entry,
      profile: { ...entry.profile, preferredRate: 25, rateCurrency: "USD" },
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
        entry={entry}
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
  })
})
