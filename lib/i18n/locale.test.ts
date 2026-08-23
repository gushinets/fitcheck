import { describe, expect, it } from "vitest"
import { resolveLocale } from "./locale"

describe("resolveLocale", () => {
  it.each([
    ["ru-RU", "ru"],
    ["ru", "ru"],
    ["RU-ru", "ru"],
    ["en-US", "en"],
    ["es", "en"],
    [undefined, "en"],
  ] as const)("maps %s to %s", (systemLocale, expected) => {
    expect(resolveLocale(systemLocale)).toBe(expected)
  })
})
