import { z } from "zod"
import { currencySchema } from "@/lib/currency"
import { jobSchema } from "@/lib/analysis/schema"

const trimmedString = (max: number) => z.string().trim().min(1).max(max)
const optionalMoney = z.number().min(0).max(100_000_000).optional()
const httpUrl = z
  .url()
  .max(2_000)
  .refine((value) => {
    const protocol = new URL(value).protocol
    return protocol === "http:" || protocol === "https:"
  }, "Only HTTP and HTTPS URLs are supported")

const vacancyFields = {
  proposalCount: jobSchema.shape.proposalCount,
  averageBid: jobSchema.shape.averageBid,
  averageBidCurrency: jobSchema.shape.averageBidCurrency,
  provenance: jobSchema.shape.provenance,
  experienceLevel: jobSchema.shape.experienceLevel,
  postedAgo: jobSchema.shape.postedAgo,
  clientRating: jobSchema.shape.clientRating,
  clientSpend: jobSchema.shape.clientSpend,
  id: trimmedString(200),
  rawSource: z.string().max(50_000).optional(),
  title: trimmedString(300),
  description: trimmedString(20_000),
  skills: z.array(trimmedString(80)).max(100),
  hourlyRateMin: optionalMoney,
  hourlyRateMax: optionalMoney,
  fixedBudget: optionalMoney,
  fixedBudgetMax: optionalMoney,
  budgetCurrency: currencySchema.optional(),
  updatedAt: z.iso.datetime(),
}

export const localAccountSchema = z.object({
  name: trimmedString(120),
  email: z.email().max(320).transform((value) => normalizeEmail(value)),
  password: z.string().min(8).max(200),
})

export const vacancyDraftSchema = z.discriminatedUnion("sourceMode", [
  z.object({
    ...vacancyFields,
    sourceMode: z.literal("url"),
    sourceUrl: httpUrl,
  }),
  z.object({
    ...vacancyFields,
    sourceMode: z.literal("text"),
    sourceUrl: httpUrl.optional(),
  }),
])

export function normalizeEmail(email: string) {
  return email.trim().toLowerCase()
}
