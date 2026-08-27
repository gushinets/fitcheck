import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { analyzeJob, AnalysisServiceError } from "./service"

const request = {
  profile: defaultProfile,
  job: detectedJob,
  locale: "en" as const,
  memory: [],
}

describe("analyzeJob", () => {
  it("normalizes a contradictory model verdict", async () => {
    const result = await analyzeJob(request, async () => ({
      ...goAnalysis,
      score: 42,
      status: "GO",
    }))

    expect(result.status).toBe("NO_GO")
  })

  it("rejects model output that violates the result contract", async () => {
    const run = analyzeJob(request, async () => ({
      ...goAnalysis,
      strengths: ["Only one"],
    }))

    await expect(run).rejects.toEqual(
      expect.objectContaining<Partial<AnalysisServiceError>>({
        code: "invalid_output",
      }),
    )
  })

  it("retries once when the first model result violates the contract", async () => {
    let attempts = 0

    const result = await analyzeJob(request, async () => {
      attempts += 1
      return attempts === 1
        ? { ...goAnalysis, strengths: ["Only one"] }
        : goAnalysis
    })

    expect(result).toEqual(goAnalysis)
    expect(attempts).toBe(2)
  })

  it("retries an invalid transport output only once", async () => {
    let attempts = 0

    const run = analyzeJob(request, async () => {
      attempts += 1
      throw new AnalysisServiceError("invalid_output", "Invalid JSON")
    })

    await expect(run).rejects.toMatchObject({ code: "invalid_output" })
    expect(attempts).toBe(2)
  })
})
