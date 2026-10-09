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
  it.each([
    ["n8n", "n8n Automation Developer Needed", "Hiring: n8n Automation Developer"],
    ["whatsapp", "Configuración Closer Ventas WhatsApp", "Necesito convertir mi línea de WhatsApp Business"],
    ["lead-generation", "B2B Lead Generation Specialist Needed", "CRITICAL REQUIREMENTS FOR APPLICANTS"],
    ["shopify", "Shopify and Foxway API Bridge Development", "bridge integration between Foxway"],
  ])("extracts the actual Freelancer %s task without bidder proposals", (name, title, description) => {
    const result = extractVacancyContent({
      finalUrl: `https://www.freelancer.com/projects/test/${name}`,
      contentType: "text/html",
      body: readFileSync(fileURLToPath(new URL(`./__fixtures__/freelancer-${name}.html`, import.meta.url)), "utf8"),
    })
    expect(result.title).toBe(title)
    expect(result.description).toContain(description)
    expect(result.description).not.toContain("Unrelated bidder proposal")
    expect(result.description).not.toContain("Hire freelancers")
  })

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
      budgetCurrency: "USD",
    })
    expect(result.description).not.toContain("Sign in")
    expect(result.description).not.toContain("Ignore all previous")
  })

  it.each(["EUR", "RUB", " eur ", "CHF", ""])("extracts supported explicit salary currency %s", (currency) => {
    const result = extractVacancyContent({
      finalUrl: "https://jobs.example/42", contentType: "text/html",
      body: fixture.replace('"currency": "USD"', `"currency": "${currency}"`),
    })
    expect(result.hourlyRateMin).toBe(40)
    expect(result.budgetCurrency).toBe(["EUR", "RUB"].includes(currency.trim().toUpperCase()) ? currency.trim().toUpperCase() : undefined)
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
