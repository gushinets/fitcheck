import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { createHistoryEntry, toCalibrationMemory, createAnalysisRequest } from "./history"

describe("website history", () => {
  it("keeps the reviewed currency in the analysis request", () => {
    const result = createAnalysisRequest({ profile: defaultProfile, locale: "ru", history: [], draft: {
      id: "draft", title: "Task", description: "Task description", skills: [], sourceMode: "text", fixedBudget: 500,
      fixedBudgetMax: 750, budgetCurrency: "EUR", updatedAt: "2026-10-09T12:00:00.000Z",
    } })
    expect(result.job).toMatchObject({ fixedBudget: 500, fixedBudgetMax: 750, budgetCurrency: "EUR" })
  })
  it("stores immutable profile and job snapshots", () => {
    const profile = structuredClone(defaultProfile)
    const job = structuredClone(detectedJob)
    const entry = createHistoryEntry({
      userId: "user-1",
      profile,
      job,
      analysis: goAnalysis,
      now: new Date("2026-08-25T12:00:00.000Z"),
    })

    profile.skills.push("Redis")
    job.title = "Changed title"

    expect(entry.profile!.skills).not.toContain("Redis")
    expect(entry.job.title).toBe("Senior Python Backend Developer")
    expect(entry.createdAt).toBe("2026-08-25T12:00:00.000Z")
  })

  it("uses only the newest ten entries as calibration memory", () => {
    const entries = Array.from({ length: 12 }, (_, index) => ({
      ...createHistoryEntry({
        userId: "user-1",
        profile: defaultProfile,
        job: { ...detectedJob, title: `Role ${index}` },
        analysis: { ...goAnalysis, score: 60 + index },
        now: new Date(index * 1_000),
      }),
      feedback:
        index === 11
          ? {
              correctedScore: 91,
              note: "Strong domain match",
              createdAt: "2026-08-25T12:00:00.000Z",
            }
          : undefined,
    }))

    const memory = toCalibrationMemory(entries)

    expect(memory).toHaveLength(10)
    expect(memory[0]).toEqual({
      jobTitle: "Role 11",
      predictedScore: 71,
      correctedScore: 91,
      note: "Strong domain match",
    })
    expect(memory.at(-1)?.jobTitle).toBe("Role 2")
  })
})

it("preserves opaque correlation locally and excludes it from calibration prompts", () => {
  const providerOperationId = "11111111-1111-4111-8111-111111111111"
  const entry = createHistoryEntry({ userId: "private-account", profile: defaultProfile, job: detectedJob, analysis: goAnalysis, providerOperationId })
  expect(entry.providerOperationId).toBe(providerOperationId)
  expect(toCalibrationMemory([entry])).toEqual([{jobTitle: detectedJob.title, predictedScore:goAnalysis.score}])
  expect(JSON.stringify(toCalibrationMemory([entry]))).not.toContain(providerOperationId)
})
