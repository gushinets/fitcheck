import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob } from "@/lib/mock-data"
import { compareHourlyRate } from "./currency"

describe("hourly rate comparison", () => {
  it("does not treat a minimum-only hourly budget as an upper limit", () => {
    expect(compareHourlyRate({ ...defaultProfile, rateCurrency: "USD", preferredRate: 35 }, {
      ...detectedJob, budgetCurrency: "USD", hourlyRateMin: 25, hourlyRateMax: undefined,
    })).toBe("unknown_hourly_ceiling")
  })
  it.each([
    ["USD", "USD", 25, "within_budget"],
    ["EUR", "EUR", 50, "within_budget"],
    ["RUB", "RUB", 51, "above_budget"],
    ["USD", "EUR", 25, "conversion_required"],
    [undefined, "USD", 25, "unknown_currency"],
    ["USD", undefined, 25, "unknown_currency"],
  ] as const)("compares %s to %s at %i without guessing exchange rates", (rateCurrency, budgetCurrency, preferredRate, expected) => {
    expect(compareHourlyRate(
      { ...defaultProfile, rateCurrency, preferredRate },
      { ...detectedJob, budgetCurrency, hourlyRateMin: 25, hourlyRateMax: 50 },
    )).toBe(expected)
  })

  it("does not compare a fixed budget with an hourly rate", () => {
    expect(compareHourlyRate({ ...defaultProfile, rateCurrency: "USD" }, {
      ...detectedJob, hourlyRateMin: undefined, hourlyRateMax: undefined,
      fixedBudget: 500, budgetCurrency: "USD",
    })).toBe("no_hourly_budget")
  })
})
