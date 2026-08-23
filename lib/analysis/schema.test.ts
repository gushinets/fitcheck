import { describe, expect, it } from "vitest"
import { analysisRequestSchema, fitAnalysisSchema } from "./schema"
import { normalizeAnalysis } from "./normalize"

const profile = {
  specialization: "Backend Developer",
  skills: ["Python", "Django"],
  experienceYears: 5,
  preferredRate: 35,
  englishLevel: "Upper Intermediate" as const,
}

const job = {
  id: "~0123456789",
  url: "https://www.upwork.com/jobs/~0123456789",
  title: "Senior Python Backend Developer",
  description: "Build and maintain a Django API for our growing product.",
  skills: ["Python", "Django"],
  hourlyRateMin: 30,
  hourlyRateMax: 50,
}

const analysis = {
  score: 82,
  status: "GO" as const,
  label: "Strong match",
  summary: "The role matches the freelancer profile.",
  strengths: ["Python match", "Rate match", "Experience match"],
  risks: ["Timezone overlap"],
  breakdown: {
    skills: 90,
    experience: 85,
    rate: 90,
    english: 70,
    requirements: 75,
  },
}

const memory = {
  jobTitle: "Previous job",
  predictedScore: 82,
  correctedScore: 65,
  note: "Timezone was a blocker",
}

describe("analysis contracts", () => {
  it("rejects more than ten calibration entries", () => {
    const result = analysisRequestSchema.safeParse({
      profile,
      job,
      locale: "en",
      memory: Array.from({ length: 11 }, () => memory),
    })

    expect(result.success).toBe(false)
  })

  it("requires exactly three strengths", () => {
    const result = fitAnalysisSchema.safeParse({
      ...analysis,
      strengths: analysis.strengths.slice(0, 2),
    })

    expect(result.success).toBe(false)
  })

  it("normalizes a score of seventy to GO", () => {
    expect(
      normalizeAnalysis({ ...analysis, score: 70, status: "NO_GO" }).status,
    ).toBe("GO")
  })

  it("normalizes a score below seventy to NO_GO", () => {
    expect(
      normalizeAnalysis({ ...analysis, score: 69, status: "GO" }).status,
    ).toBe("NO_GO")
  })
})
