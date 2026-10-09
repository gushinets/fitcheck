import { describe, expect, it } from "vitest"
import { formatRateRange } from "./currency"

describe("hourly range display", () => {
  it.each([[25, 50, "25–50"], [25, undefined, "25+"], [undefined, 50, "≤50"], [0, 0, "0–0"]] as const)(
    "preserves open bounds %s / %s", (min, max, expected) => {
      expect(formatRateRange(min, max)).toBe(expected)
    },
  )
})
