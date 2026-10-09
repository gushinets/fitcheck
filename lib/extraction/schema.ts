import { z } from "zod"
import { currencySchema } from "@/lib/currency"

const publicUrl = z
  .url()
  .max(2_000)
  .refine((value) => {
    const protocol = new URL(value).protocol
    return protocol === "http:" || protocol === "https:"
  })

export const extractRequestSchema = z.object({ url: publicUrl })

export const extractedVacancySchema = z.object({
  sourceUrl: publicUrl,
  title: z.string().trim().min(1).max(300),
  description: z.string().trim().min(1).max(20_000),
  skills: z.array(z.string().trim().min(1).max(80)).max(100),
  hourlyRateMin: z.number().min(0).max(100_000).optional(),
  hourlyRateMax: z.number().min(0).max(100_000).optional(),
  fixedBudget: z.number().min(0).max(100_000_000).optional(),
  budgetCurrency: currencySchema.optional(),
})

export type ExtractedVacancy = z.infer<typeof extractedVacancySchema>
