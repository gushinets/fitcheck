import { describe, expect, it } from "vitest"
import { webMessages } from "./web-messages"

describe("website messages", () => {
  it("keeps Russian and English dictionaries structurally identical", () => {
    expect(Object.keys(webMessages.ru).sort()).toEqual(
      Object.keys(webMessages.en).sort(),
    )
  })
})
