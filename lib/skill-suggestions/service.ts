import { z } from "zod"
import {
  skillSuggestionResponseSchema,
  type SkillSuggestionRequest,
  type SkillSuggestionResponse,
} from "./schema"

export type SkillSuggestionErrorCode =
  | "rate_limit"
  | "timeout"
  | "invalid_output"
  | "upstream"

export class SkillSuggestionServiceError extends Error {
  constructor(
    public readonly code: SkillSuggestionErrorCode,
    message: string,
  ) {
    super(message)
    this.name = "SkillSuggestionServiceError"
  }
}

export type SkillSuggestionTransport = (
  request: SkillSuggestionRequest,
) => Promise<unknown>

const providerResponseSchema = z.object({
  skills: z.array(z.string()),
})

function normalizeSkills(skills: string[]) {
  const seen = new Set<string>()
  const normalized: string[] = []

  for (const value of skills) {
    const skill = value.trim()
    if (!skill) continue

    const key = skill.toLocaleLowerCase()
    if (seen.has(key)) continue

    seen.add(key)
    normalized.push(skill)
    if (normalized.length === 10) break
  }

  return normalized
}

export async function suggestSkills(
  request: SkillSuggestionRequest,
  transport: SkillSuggestionTransport,
): Promise<SkillSuggestionResponse> {
  const raw = await transport(request)
  const providerResponse = providerResponseSchema.safeParse(raw)
  if (!providerResponse.success) {
    throw new SkillSuggestionServiceError(
      "invalid_output",
      "Model output failed validation",
    )
  }

  const result = skillSuggestionResponseSchema.safeParse({
    skills: normalizeSkills(providerResponse.data.skills),
  })
  if (!result.success) {
    throw new SkillSuggestionServiceError(
      "invalid_output",
      "Model output failed validation",
    )
  }

  return result.data
}
