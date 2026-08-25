// @vitest-environment node

import { describe, expect, it } from "vitest"
import { ExtractionNetworkError } from "@/lib/extraction/network"
import { createExtractHandler } from "./handler"

describe("POST /api/extract", () => {
  it("returns a normalized vacancy without raw HTML", async () => {
    const handler = createExtractHandler({
      fetchPage: async () => ({
        finalUrl: "https://jobs.example/role",
        contentType: "text/html",
        body: "<main><h1>Backend Engineer</h1><p>Build reliable APIs for a production SaaS platform.</p></main>",
      }),
    })

    const response = await handler(request({ url: "https://jobs.example/role" }))

    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toEqual({
      sourceUrl: "https://jobs.example/role",
      title: "Backend Engineer",
      description: "Build reliable APIs for a production SaaS platform.",
      skills: [],
    })
  })

  it("offers manual entry when extracted content is insufficient", async () => {
    const handler = createExtractHandler({
      fetchPage: async () => ({
        finalUrl: "https://jobs.example/role",
        contentType: "text/html",
        body: "<h1>Role</h1>",
      }),
    })

    const response = await handler(request({ url: "https://jobs.example/role" }))

    expect(response.status).toBe(422)
    await expect(response.json()).resolves.toEqual({
      error: "extraction_insufficient",
    })
  })

  it("rejects invalid JSON and invalid URLs", async () => {
    const handler = createExtractHandler({ fetchPage: async () => neverPage })
    const invalidJson = new Request("http://localhost:3000/api/extract", {
      method: "POST",
      body: "{",
    })

    expect((await handler(invalidJson)).status).toBe(400)
    expect((await handler(request({ url: "file:///etc/passwd" }))).status).toBe(400)
  })

  it.each([
    ["blocked_address", 403],
    ["unsupported_content", 415],
    ["response_too_large", 413],
    ["timeout", 504],
    ["redirect_limit", 502],
    ["fetch_failed", 502],
  ] as const)("maps %s to HTTP %i", async (code, status) => {
    const handler = createExtractHandler({
      fetchPage: async () => {
        throw new ExtractionNetworkError(code)
      },
    })

    const response = await handler(request({ url: "https://jobs.example/role" }))

    expect(response.status).toBe(status)
    await expect(response.json()).resolves.toEqual({ error: code })
  })
})

const neverPage = {
  finalUrl: "https://jobs.example/role",
  contentType: "text/plain",
  body: "This result must never be used.",
}

function request(body: unknown) {
  return new Request("http://localhost:3000/api/extract", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })
}
