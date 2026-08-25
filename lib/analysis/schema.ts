import { z } from "zod"

const trimmedString = (max: number) => z.string().trim().min(1).max(max)
const scoreSchema = z.number().int().min(0).max(100)

export const englishLevelSchema = z.enum([
  "Basic",
  "Intermediate",
  "Upper Intermediate",
  "Advanced",
  "Fluent",
])

export const freelancerProfileSchema = z.object({
  specialization: trimmedString(120),
  skills: z.array(trimmedString(80)).min(1).max(50),
  experienceYears: z.number().min(0).max(60),
  preferredRate: z.number().min(0).max(1000),
  englishLevel: englishLevelSchema,
})

export const jobSchema = z.object({
  id: trimmedString(200),
  url: z.url().max(2000).optional(),
  title: trimmedString(300),
  description: trimmedString(20_000),
  skills: z.array(trimmedString(80)).max(100),
  hourlyRateMin: z.number().min(0).max(100_000).optional(),
  hourlyRateMax: z.number().min(0).max(100_000).optional(),
  fixedBudget: z.number().min(0).max(100_000_000).optional(),
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
  strengths: z.array(trimmedString(240)).length(3),
  risks: z.array(trimmedString(240)).max(3),
  breakdown: z.object({
    skills: scoreSchema,
    experience: scoreSchema,
    rate: scoreSchema,
    english: scoreSchema,
    requirements: scoreSchema,
  }),
})
