import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob } from "@/lib/mock-data"
import type { AnalysisRequest } from "@/lib/types"
import { buildAnalysisPrompt } from "./prompt"

function request(overrides: Partial<AnalysisRequest> = {}): AnalysisRequest {
  return {
    profile: defaultProfile,
    job: detectedJob,
    locale: "en",
    memory: [],
    ...overrides,
  }
}

describe("buildAnalysisPrompt", () => {
  it("marks absent job fields instead of inventing values", () => {
    const prompt = buildAnalysisPrompt(
      request({
        job: {
          ...detectedJob,
          hourlyRateMin: undefined,
          hourlyRateMax: undefined,
          fixedBudget: undefined,
          clientRating: undefined,
        },
      }),
    )

    expect(prompt.input).toContain("Hourly rate: not provided")
    expect(prompt.input).toContain("Fixed budget: not provided")
    expect(prompt.input).toContain("Client rating: not provided")
  })

  it("requests Russian user-visible fields for Russian locale", () => {
    const prompt = buildAnalysisPrompt(request({ locale: "ru" }))

    expect(prompt.instructions).toContain(
      "Write all user-visible fields in Russian",
    )
  })

  it("includes user corrections as calibration rather than facts", () => {
    const prompt = buildAnalysisPrompt(
      request({
        memory: [
          {
            jobTitle: "US timezone role",
            predictedScore: 82,
            correctedScore: 55,
            note: "Timezone overlap is a blocker",
          },
        ],
      }),
    )

    expect(prompt.input).toContain("Predicted score: 82")
    expect(prompt.input).toContain("User-corrected score: 55")
    expect(prompt.input).toContain("Use memory only to calibrate")
  })
})
