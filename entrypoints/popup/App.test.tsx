import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import type { ExtensionRuntime } from "@/lib/extension/runtime"
import { App } from "./App"

const runtime: ExtensionRuntime = {
  async getLocale() { return "en" },
  async loadState() { return { version: 1, profile: defaultProfile, history: [] } },
  async getCurrentJob() { return { ok: true, job: detectedJob } },
  async analyze() { return goAnalysis },
  async saveProfile() {},
  async resetProfile() {},
  async addAnalysis() {},
  async saveFeedback() {},
  async clearHistory() {},
  async applyToJob() {},
  closePopup() {},
}

describe("popup App", () => {
  it("renders the extension UI with an injected runtime", async () => {
    render(<App runtime={runtime} />)

    expect(await screen.findByText("FitCheck")).toBeVisible()
    expect(await screen.findByRole("button", { name: /analyze job/i })).toBeVisible()
  })
})
