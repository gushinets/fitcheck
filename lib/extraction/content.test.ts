// @vitest-environment node

import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { extractVacancyContent } from "./content"

const fixture = readFileSync(
  fileURLToPath(new URL("./__fixtures__/job-page.html", import.meta.url)),
  "utf8",
)

describe("vacancy content extraction", () => {
  it("prefers structured JobPosting fields and removes page chrome", () => {
    const result = extractVacancyContent({
      finalUrl: "https://jobs.example/42",
      contentType: "text/html",
      body: fixture,
    })

    expect(result).toEqual({
      sourceUrl: "https://jobs.example/42",
      title: "Senior TypeScript Engineer",
      description:
        "Build and maintain a multi-tenant SaaS platform.\nWork with a distributed product team.",
      skills: ["TypeScript", "React", "PostgreSQL"],
      hourlyRateMin: 40,
      hourlyRateMax: 60,
    })
    expect(result.description).not.toContain("Sign in")
    expect(result.description).not.toContain("Ignore all previous")
  })

  it("extracts a title and description from plain text", () => {
    const result = extractVacancyContent({
      finalUrl: "https://plain.example/job",
      contentType: "text/plain",
      body: "\nBackend API Developer\n\nBuild reliable APIs.\nOwn database performance.\n",
    })

    expect(result).toEqual({
      sourceUrl: "https://plain.example/job",
      title: "Backend API Developer",
      description: "Build reliable APIs.\nOwn database performance.",
      skills: [],
    })
  })
})
