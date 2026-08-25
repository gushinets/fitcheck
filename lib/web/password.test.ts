import { describe, expect, it } from "vitest"
import { derivePassword, verifyPassword } from "./password"

describe("local password derivation", () => {
  it("uses a unique salt and verifies only the matching password", async () => {
    const first = await derivePassword("correct horse battery staple")
    const second = await derivePassword("correct horse battery staple")

    expect(first.salt).not.toBe(second.salt)
    await expect(
      verifyPassword("correct horse battery staple", first),
    ).resolves.toBe(true)
    await expect(verifyPassword("wrong password", first)).resolves.toBe(false)
  })
})
