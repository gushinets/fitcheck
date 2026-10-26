import { z } from "zod"
import type { Locale } from "@/lib/types"

const skillSchema = z.string().trim().min(1).max(80)

export type SkillSuggestionRequest = {
  specialization: string
  locale: Locale
}

export type SkillSuggestionResponse = {
  skills: string[]
}

export const skillSuggestionRequestSchema: z.ZodType<SkillSuggestionRequest> =
  z.object({
    specialization: z.string().trim().min(1).max(120),
    locale: z.enum(["en", "ru"]),
  })

export const skillSuggestionResponseSchema: z.ZodType<SkillSuggestionResponse> =
  z.object({
    skills: z.array(skillSchema).max(10),
  })
