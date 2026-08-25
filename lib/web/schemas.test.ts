import { describe, expect, it } from "vitest"
import { normalizeEmail, vacancyDraftSchema } from "./schemas"

describe("website schemas", () => {
  it("normalizes local account emails", () => {
    expect(normalizeEmail("  Person@Example.COM ")).toBe("person@example.com")
  })

  it("accepts a manual vacancy without a source URL", () => {
    const draft = vacancyDraftSchema.parse({
      id: "draft-1",
      sourceMode: "text",
      title: "Senior TypeScript Engineer",
      description: "Build and maintain a multi-tenant SaaS application.",
      skills: ["TypeScript"],
      updatedAt: "2026-08-25T12:00:00.000Z",
    })

    expect(draft.sourceMode).toBe("text")
    expect(draft.sourceUrl).toBeUndefined()
  })

  it("requires an HTTP URL for URL vacancies", () => {
    expect(() =>
      vacancyDraftSchema.parse({
        id: "draft-2",
        sourceMode: "url",
        sourceUrl: "file:///etc/passwd",
        title: "Backend Engineer",
        description: "Build and maintain a production backend service.",
        skills: [],
        updatedAt: "2026-08-25T12:00:00.000Z",
      }),
    ).toThrow()
  })
})
