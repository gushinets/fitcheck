import { describe, expect, it } from "vitest"
import {
  analysisRequestSchema,
  fitAnalysisSchema,
  freelancerProfileSchema,
} from "./schema"
import { normalizeAnalysis } from "./normalize"

const profile = {
  specialization: "Backend Developer",
  skills: ["Python", "Django"],
  experienceYears: 5,
  preferredRate: 35,
  desiredMonthlyIncome: 5_000,
  workFormats: ["remote"] as const,
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
  it("accepts a profile without monthly income", () => {
    const current = { ...profile }
    Reflect.deleteProperty(current, "desiredMonthlyIncome")
    expect(freelancerProfileSchema.safeParse(current).success).toBe(true)
  })

  it("discards monthly income from legacy analysis requests", () => {
    const parsed = analysisRequestSchema.parse({ profile, job, locale: "en", memory: [] })
    expect(parsed.profile).not.toHaveProperty("desiredMonthlyIncome")
  })
  it.each(["USD", "EUR", "RUB"])("retains %s independently on the profile and task", (currency) => {
    const result = analysisRequestSchema.parse({ profile: { ...profile, rateCurrency: currency }, job: { ...job, budgetCurrency: currency }, locale: "ru", memory: [] })
    expect(result.profile.rateCurrency).toBe(currency)
    expect(result.job.budgetCurrency).toBe(currency)
  })

  it.each(["CHF", "usd", null])("rejects unsupported explicit currency %s", (currency) => {
    expect(freelancerProfileSchema.safeParse({ ...profile, rateCurrency: currency }).success).toBe(false)
    expect(analysisRequestSchema.safeParse({ profile, job: { ...job, budgetCurrency: currency }, locale: "en", memory: [] }).success).toBe(false)
  })
  it("retains each skill's proficiency and rejects invalid levels", () => {
    expect(freelancerProfileSchema.parse({
      ...profile, skillLevels: { python: "primary", django: "basic" },
    })).toMatchObject({ skillLevels: { python: "primary", django: "basic" } })
    expect(freelancerProfileSchema.safeParse({
      ...profile, skillLevels: { python: "expert" },
    }).success).toBe(false)
  })

  it("preserves proficiency for prototype-like skill names", () => {
    const levels = Object.fromEntries([["__proto__", "basic"], ["constructor", "confident"]])
    const parsed = freelancerProfileSchema.parse({ ...profile, skills: ["__proto__", "constructor"], skillLevels: levels })
    expect(Object.entries(parsed.skillLevels ?? {})).toEqual([["__proto__", "basic"], ["constructor", "confident"]])
  })

  it("rejects proficiency for a skill missing from the profile", () => {
    expect(freelancerProfileSchema.safeParse({
      ...profile, skillLevels: { n8n: "primary" },
    }).success).toBe(false)
  })

  it("accepts an hourly rate of 2500", () => {
    expect(
      freelancerProfileSchema.safeParse({ ...profile, preferredRate: 2500 })
        .success,
    ).toBe(true)
  })

  it("rejects negative and non-finite monetary values", () => {
    expect(
      freelancerProfileSchema.safeParse({ ...profile, preferredRate: -1 })
        .success,
    ).toBe(false)
    expect(
      freelancerProfileSchema.safeParse({
        ...profile,
        preferredRate: Number.POSITIVE_INFINITY,
      }).success,
    ).toBe(false)
  })

  it("requires at least one unique valid work format", () => {
    expect(
      freelancerProfileSchema.safeParse({ ...profile, workFormats: [] }).success,
    ).toBe(false)
    expect(
      freelancerProfileSchema.safeParse({
        ...profile,
        workFormats: ["remote", "remote"],
      }).success,
    ).toBe(false)
    expect(
      freelancerProfileSchema.safeParse({
        ...profile,
        workFormats: ["elsewhere"],
      }).success,
    ).toBe(false)
  })

  it("rejects more than ten calibration entries", () => {
    const result = analysisRequestSchema.safeParse({
      profile,
      job,
      locale: "en",
      memory: Array.from({ length: 11 }, () => memory),
    })

    expect(result.success).toBe(false)
  })

  it("allows fewer confirmed strengths and rejects forced extra ones", () => {
    const result = fitAnalysisSchema.safeParse({
      ...analysis,
      strengths: analysis.strengths.slice(0, 2),
    })

    expect(result.success).toBe(true)
    expect(fitAnalysisSchema.safeParse({ ...analysis, strengths: [] }).success).toBe(true)
    expect(fitAnalysisSchema.safeParse({ ...analysis, strengths: [...analysis.strengths, "Fourth"] }).success).toBe(false)
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
