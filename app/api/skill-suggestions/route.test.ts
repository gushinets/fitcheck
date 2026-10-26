// @vitest-environment node
import { expect, it } from "vitest"
import { OPTIONS, POST } from "./route"
it("does not expose the retired suggestion provider through POST or preflight", () => {
  expect(POST().status).toBe(410)
  expect(OPTIONS().status).toBe(410)
  expect(OPTIONS().headers.get("access-control-allow-origin")).toBeNull()
})
