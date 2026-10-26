import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { analyzeJob, AnalysisServiceError } from "./service"
import type { AnalysisTransport } from "./service"
import type { AnalysisRequest } from "@/lib/types"

const request = {
  profile: defaultProfile,
  job: detectedJob,
  locale: "en" as const,
  memory: [],
}

describe("analyzeJob", () => {
  it("ignores legacy monthly income in generation and grounding inputs", async () => {
    const inputs: unknown[] = []
    const prompts: unknown[] = []
    const transport: AnalysisTransport = Object.assign(async (input: AnalysisRequest, prompt: unknown) => {
      inputs.push(input.profile)
      prompts.push(prompt)
      return { ...goAnalysis, strengths: [] }
    }, { verifyGrounding: async (input: AnalysisRequest) => {
      inputs.push(input.profile)
      return true
    } })
    const firstProfile = { ...defaultProfile, desiredMonthlyIncome: 1000 }
    const secondProfile = { ...defaultProfile, desiredMonthlyIncome: 900000 }
    const first = await analyzeJob({ ...request, profile: firstProfile }, transport)
    const second = await analyzeJob({ ...request, profile: secondProfile }, transport)
    expect(first).toEqual(second)
    expect(prompts[0]).toEqual(prompts[1])
    for (const profile of inputs) expect(profile).not.toHaveProperty("desiredMonthlyIncome")
  })
  it("passes grounding rejection reasons to the second generation", async () => {
    const prompts: string[] = []
    const transport: AnalysisTransport = Object.assign(async (_request: unknown, prompt: { instructions: string }) => {
      prompts.push(prompt.instructions)
      return { ...goAnalysis, strengths: [] }
    }, { verifyGrounding: async () => ({ supported: prompts.length === 2, unsupportedClaims: prompts.length === 1 ? ["You must speak Czech"] : [] }) })
    await analyzeJob(request, transport)
    expect(prompts[1]).toContain("You must speak Czech")
  })
  it("tells the retry which output limits were violated", async () => {
    const prompts: string[] = []
    await analyzeJob(request, async (_request, prompt) => {
      prompts.push(prompt.instructions)
      return { ...goAnalysis, strengths: [], summary: prompts.length === 1 ? "x".repeat(801) : "Supported summary." }
    })
    expect(prompts[1]).toContain("summary")
    expect(prompts[1]).toContain("800")
    expect(prompts[1]).toContain("previous response")
  })
  it("renders selected evidence from the profile and retains its provenance", async () => {
    const result = await analyzeJob(request, async () => ({ ...goAnalysis, strengths: ["skill:0"] }))
    expect(result.strengths).toEqual(["Your profile lists Python; this skill appears in the task. Proficiency is not specified."])
    expect(result.strengthEvidence).toEqual([{ id: "skill:0", profileFields: ["skills.0"], taskFields: ["skills", "title"] }])
  })

  it("accepts no strengths rather than inventing advantages", async () => {
    const result = await analyzeJob(request, async () => ({ ...goAnalysis, strengths: [] }))
    expect(result.strengths).toEqual([])
  })

  it.each([{ strengths: ["ESP32 expertise", "LoRa expertise", "Rhino expertise"] }, { strengths: ["skill:99"] }, { strengths: ["skill:0", "skill:0"] }])("rejects unsupported or duplicate strength evidence $strengths", async ({ strengths }) => {
    await expect(analyzeJob(request, async () => ({ ...goAnalysis, strengths }))).rejects.toMatchObject({ code: "invalid_output" })
  })

  it("rejects a Czech-language claim failed by the narrative grounding check", async () => {
    const transport: AnalysisTransport = Object.assign(async () => ({ ...goAnalysis, strengths: ["skill:0", "skill:1", "skill:3"], risks: ["You must speak Czech to generate CZ product descriptions."] }), {
      verifyGrounding: async () => false,
    })
    await expect(analyzeJob(request, transport)).rejects.toMatchObject({ code: "invalid_output" })
  })

  it("audits the final profile-derived strengths and retries unsupported narrative once", async () => {
    let checks = 0
    let checkedStrengths: string[] = []
    const transport: AnalysisTransport = Object.assign(async () => ({ ...goAnalysis, strengths: ["skill:0"] }), {
      verifyGrounding: async (_request: unknown, analysis: { strengths: string[] }) => {
        checkedStrengths = analysis.strengths
        return ++checks === 2
      },
    })
    const result = await analyzeJob(request, transport)
    expect(checkedStrengths).toEqual(result.strengths)
    expect(checks).toBe(2)
  })
  it("normalizes a contradictory model verdict", async () => {
    const result = await analyzeJob(request, async () => ({
      ...goAnalysis,
      strengths: [],
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
        : { ...goAnalysis, strengths: [] }
    })

    expect(result).toMatchObject({ ...goAnalysis, strengths: [], strengthEvidence: [] })
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
