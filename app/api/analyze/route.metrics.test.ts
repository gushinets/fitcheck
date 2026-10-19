// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest"
import { POST as analyze } from "./route"
import { POST as extract } from "../extract/route"
import { POST as suggest } from "../skill-suggestions/route"
afterEach(() => vi.unstubAllGlobals())
it.each([analyze, extract, suggest])("retired routes cannot bypass server auth or quotas", async route => {
  const provider = vi.fn()
  vi.stubGlobal("fetch", provider)
  const response = route()
  expect(response.status).toBe(410)
  expect(response.headers.get("cache-control")).toBe("no-store")
  expect(provider).not.toHaveBeenCalled()
})
