import { describe, expect, it } from "vitest"
import { extractDescriptionFields } from "./fields"

describe("task fields in free text", () => {
  it.each([
    ["Budget: €250–750", { fixedBudget: 250, fixedBudgetMax: 750, budgetCurrency: "EUR" }],
    ["Project budget: $250-750 USD", { fixedBudget: 250, fixedBudgetMax: 750, budgetCurrency: "USD" }],
    ["Бюджет: 25 000–75 000 RUB", { fixedBudget: 25000, fixedBudgetMax: 75000, budgetCurrency: "RUB" }],
    ["Budget: EUR 1,250.50 – 2,000.75", { fixedBudget: 1250.5, fixedBudgetMax: 2000.75, budgetCurrency: "EUR" }],
    ["Бюджет: 1500,50 ₽", { fixedBudget: 1500.5, budgetCurrency: "RUB" }],
    ["Rate: $25–$50/hour", { hourlyRateMin: 25, hourlyRateMax: 50, budgetCurrency: "USD" }],
    ["Ставка: 2500 руб./час", { hourlyRateMin: 2500, hourlyRateMax: 2500, budgetCurrency: "RUB" }],
    ["€250–750", { fixedBudget: 250, fixedBudgetMax: 750, budgetCurrency: "EUR" }],
    ["Budget: 250–750", { fixedBudget: 250, fixedBudgetMax: 750 }],
    ["$25–50/hr", { hourlyRateMin: 25, hourlyRateMax: 50, budgetCurrency: "USD" }],
    ["Hourly rate: from $25/hour", { hourlyRateMin: 25, budgetCurrency: "USD" }],
    ["Hourly rate: up to $50/hour", { hourlyRateMax: 50, budgetCurrency: "USD" }],
    ["Hourly rate: $25 per hour", { hourlyRateMin: 25, hourlyRateMax: 25, budgetCurrency: "USD" }],
    ["Budget: $500 for this project", { fixedBudget: 500, budgetCurrency: "USD" }],
    ["Budget: EUR 1.250–2.500", { fixedBudget: 1250, fixedBudgetMax: 2500, budgetCurrency: "EUR" }],
  ] as const)("extracts %s", (text, expected) => {
    expect(extractDescriptionFields(text)).toEqual({ skills: [], ...expected })
  })

  it.each(["3. Your project-based or hourly rate", "2–3 examples, 5 years of experience", "Products cost €250–750", "Client spend: $5000", "Average bid: $300", "Budget: $250–750 CAD", "Budget: €750–250", "Budget: €1000000000"])("does not invent task budget from %s", (text) => {
    expect(extractDescriptionFields(text)).toEqual({ skills: [] })
  })

  it("extracts explicit skill lists and known tools from the description", () => {
    expect(extractDescriptionFields("Skills: Cold outreach, Lead generation\nBuild n8n workflows with Make.com and Google Sheets.").skills)
      .toEqual(expect.arrayContaining(["Cold outreach", "Lead generation", "n8n", "Make.com", "Google Sheets"]))
  })

  it("reads a skill list on the line after its label", () => {
    expect(extractDescriptionFields("Required skills:\nCold outreach, Sales prospecting\n\nBudget: €250–750").skills).toEqual(["Cold outreach", "Sales prospecting"])
  })
})
