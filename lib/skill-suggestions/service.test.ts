import { describe, expect, it } from "vitest"
import {
  skillSuggestionRequestSchema,
  skillSuggestionResponseSchema,
} from "./schema"
import { SkillSuggestionServiceError, suggestSkills } from "./service"

const request = {
  specialization: "Backend Developer",
  locale: "en" as const,
}

describe("skill suggestion contracts", () => {
  it("accepts a localized specialization request and no more than ten skills", () => {
    expect(skillSuggestionRequestSchema.safeParse(request).success).toBe(true)
    expect(
      skillSuggestionResponseSchema.safeParse({
        skills: Array.from({ length: 10 }, (_, index) => `Skill ${index + 1}`),
      }).success,
    ).toBe(true)
    expect(
      skillSuggestionResponseSchema.safeParse({
        skills: Array.from({ length: 11 }, (_, index) => `Skill ${index + 1}`),
      }).success,
    ).toBe(false)
  })
})

describe("suggestSkills", () => {
  it("trims values, removes case-insensitive duplicates, and keeps the first ten", async () => {
    const result = await suggestSkills(request, async () => ({
      skills: [
        " Python ",
        "python",
        " FastAPI ",
        "PostgreSQL",
        "Docker",
        "Redis",
        "Celery",
        "Git",
        "REST API",
        "Linux",
        "Testing",
        "AWS",
      ],
    }))

    expect(result).toEqual({
      skills: [
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Docker",
        "Redis",
        "Celery",
        "Git",
        "REST API",
        "Linux",
        "Testing",
      ],
    })
  })

  it("skips whitespace-only entries among valid skills", async () => {
    const result = await suggestSkills(request, async () => ({
      skills: [" Python ", "   ", "\t", " FastAPI ", "\n"],
    }))

    expect(result).toEqual({ skills: ["Python", "FastAPI"] })
  })

  it("rejects malformed provider output", async () => {
    const run = suggestSkills(request, async () => ({ skills: ["Python", 42] }))

    await expect(run).rejects.toEqual(
      expect.objectContaining<Partial<SkillSuggestionServiceError>>({
        code: "invalid_output",
      }),
    )
  })
})
