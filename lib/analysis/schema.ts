import { z } from "zod"
import type { FreelancerProfile } from "@/lib/types"
import { currencySchema } from "@/lib/currency"

const trimmedString = (max: number) => z.string().trim().min(1).max(max)
const scoreSchema = z.number().int().min(0).max(100)
const moneySchema = z.number().finite().min(0).max(100_000_000)

export const englishLevelSchema = z.enum([
  "Basic",
  "Intermediate",
  "Upper Intermediate",
  "Advanced",
  "Fluent",
])

export const workFormatSchema = z.enum(["remote", "office", "hybrid"])
export const skillLevelSchema = z.enum(["primary", "confident", "basic"])

// Validate entries as a Map so Zod does not discard an own "__proto__" skill.
const skillLevelsSchema = z.preprocess(
  (value) => Object.prototype.toString.call(value) === "[object Object]"
    ? new Map(Object.entries(value as Record<string, unknown>))
    : null,
  z.map(trimmedString(80), skillLevelSchema).transform((levels) => Object.fromEntries(levels)),
)

export const freelancerProfileSchema = z.object({
  specialization: trimmedString(120),
  skills: z.array(trimmedString(80)).min(1).max(50),
  skillLevels: skillLevelsSchema.optional(),
  experienceYears: z.number().min(0).max(60),
  preferredRate: moneySchema,
  rateCurrency: currencySchema.optional(),
  desiredMonthlyIncome: moneySchema,
  workFormats: z
    .array(workFormatSchema)
    .min(1)
    .refine(
      (formats) => new Set(formats).size === formats.length,
      "Work formats must be unique",
    ),
  englishLevel: englishLevelSchema,
}).refine(
  (profile) => Object.keys(profile.skillLevels ?? {}).every(
    (key) => key === key.toLowerCase() && profile.skills.some((skill) => skill.toLowerCase() === key),
  ),
  { message: "Skill levels must refer to skills in the profile", path: ["skillLevels"] },
)

export function normalizeFreelancerProfile(value: unknown): FreelancerProfile {
  const candidate = value as Partial<FreelancerProfile>
  return freelancerProfileSchema.parse({
    ...candidate,
    desiredMonthlyIncome: candidate.desiredMonthlyIncome ?? 0,
    workFormats: candidate.workFormats ?? ["remote"],
  })
}

export const jobSchema = z.object({
  id: trimmedString(200),
  url: z.url().max(2000).optional(),
  title: trimmedString(300),
  description: trimmedString(20_000),
  skills: z.array(trimmedString(80)).max(100),
  hourlyRateMin: z.number().min(0).max(100_000).optional(),
  hourlyRateMax: z.number().min(0).max(100_000).optional(),
  fixedBudget: z.number().min(0).max(100_000_000).optional(),
  fixedBudgetMax: z.number().min(0).max(100_000_000).optional(),
  budgetCurrency: currencySchema.optional(),
  experienceLevel: trimmedString(100).optional(),
  postedAgo: trimmedString(100).optional(),
  clientRating: z.number().min(0).max(5).optional(),
  clientSpend: z.number().min(0).max(10_000_000_000).optional(),
})

export const calibrationEntrySchema = z.object({
  jobTitle: trimmedString(300),
  predictedScore: scoreSchema,
  correctedScore: scoreSchema.optional(),
  note: z.string().trim().max(500).optional(),
})

export const analysisRequestSchema = z.object({
  profile: freelancerProfileSchema,
  job: jobSchema,
  locale: z.enum(["en", "ru"]),
  memory: z.array(calibrationEntrySchema).max(10),
})

export const fitAnalysisSchema = z.object({
  score: scoreSchema,
  status: z.enum(["GO", "NO_GO"]),
  label: trimmedString(80),
  summary: trimmedString(800),
  strengths: z.array(trimmedString(240)).max(3),
  strengthEvidence: z.array(z.object({ id: trimmedString(120), profileFields: z.array(trimmedString(120)).min(1), taskFields: z.array(trimmedString(120)).min(1) })).max(3).optional(),
  risks: z.array(trimmedString(240)).max(3),
  breakdown: z.object({
    skills: scoreSchema,
    experience: scoreSchema,
    rate: scoreSchema,
    english: scoreSchema,
    requirements: scoreSchema,
  }),
})
