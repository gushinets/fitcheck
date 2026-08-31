import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import type { HistoryEntry } from "@/lib/types"
import type { ExtensionRuntime } from "@/lib/extension/runtime"
import { ExtensionApp } from "./extension-app"

function runtime(
  overrides: Partial<ExtensionRuntime> = {},
): ExtensionRuntime & { savedEntries: HistoryEntry[] } {
  const savedEntries: HistoryEntry[] = []
  return {
    savedEntries,
    async getLocale() {
      return "en"
    },
    async loadState() {
      return { version: 1, profile: defaultProfile, history: [] }
    },
    async getCurrentJob() {
      return { ok: true, job: detectedJob }
    },
    async analyze() {
      return goAnalysis
    },
    async saveProfile() {},
    async resetProfile() {},
    async addAnalysis(entry) {
      savedEntries.push(entry)
    },
    async saveFeedback() {},
    async clearHistory() {},
    async applyToJob() {},
    closePopup() {},
    ...overrides,
  }
}

describe("ExtensionApp", () => {
  it("stores and displays a successful analysis", async () => {
    const user = userEvent.setup()
    const testRuntime = runtime()
    render(<ExtensionApp runtime={testRuntime} />)

    await user.click(
      await screen.findByRole("button", { name: /analyze task/i }),
    )

    expect(await screen.findByLabelText("Fit score 82 out of 100")).toBeVisible()
    expect(testRuntime.savedEntries).toHaveLength(1)
  })

  it("shows an unsupported state outside an Upwork task", async () => {
    const testRuntime = runtime({
      async getCurrentJob() {
        return { ok: false, reason: "unsupported" }
      },
    })

    render(<ExtensionApp runtime={testRuntime} />)

    expect(await screen.findByText("Open an Upwork task")).toBeVisible()
  })

  it("does not store a failed analysis", async () => {
    const user = userEvent.setup()
    const testRuntime = runtime({
      async analyze() {
        throw new Error("network")
      },
    })
    render(<ExtensionApp runtime={testRuntime} />)

    await user.click(
      await screen.findByRole("button", { name: /analyze task/i }),
    )

    expect(await screen.findByRole("button", { name: /try again/i })).toBeVisible()
    expect(testRuntime.savedEntries).toHaveLength(0)
  })

  it("shows onboarding when no profile is stored", async () => {
    const testRuntime = runtime({
      async loadState() {
        return { version: 1, profile: null, history: [] }
      },
    })

    render(<ExtensionApp runtime={testRuntime} />)

    expect(await screen.findByText("Set up your profile")).toBeVisible()
  })
})
