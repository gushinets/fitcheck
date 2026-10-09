import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob } from "@/lib/mock-data"
import { ReadyScreen } from "./ready-screen"

describe("extension currency display", () => {
  it("displays the supplied currencies without replacing them with dollars", () => {
    render(<ReadyScreen profile={{ ...defaultProfile, rateCurrency: "EUR" }} job={{ ...detectedJob, budgetCurrency: "RUB" }} onAnalyze={() => {}} />)
    expect(screen.getByText(/35 EUR\/hr/)).toBeVisible()
    expect(screen.getByText("30–50 RUB/hr")).toBeVisible()
  })
})
