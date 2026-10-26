// @vitest-environment node

import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { ExtractionNetworkError, fetchPublicPage } from "@/lib/extraction/network"
import { createExtractHandler } from "./handler"

describe("POST /api/extract", () => {
  it.each([
    ["n8n", "n8n/Automation-Developer-Needed-40731652", "n8n Automation Developer Needed"],
    ["whatsapp", "chatbot-development/Configuraci-Closer-Ventas-WhatsApp", "Configuración Closer Ventas WhatsApp"],
    ["lead-generation", "b2b-marketing/Lead-Generation-Specialist-Needed-40730738", "B2B Lead Generation Specialist Needed"],
    ["shopify", "shopify-site/Shopify-Foxway-API-Bridge-Development", "Shopify and Foxway API Bridge Development"],
  ])("loads and parses the report's %s link after its redirect", async (name, path, title) => {
    const body = readFileSync(fileURLToPath(new URL(`../../../lib/extraction/__fixtures__/freelancer-${name}.html`, import.meta.url)), "utf8") + `<!--${"x".repeat(1_400_000)}-->`
    const handler = createExtractHandler({
      fetchPage: (url) => fetchPublicPage(url, {
        resolve: async () => [{ address: "93.184.216.34", family: 4 }],
        request: async (target, _addresses, limits) => {
          if (target.pathname.endsWith(".html")) {
            return { status: 301, headers: { location: target.pathname.slice(0, -5) }, body: "" }
          }
          if (Buffer.byteLength(body) > limits.maxBytes) throw new ExtractionNetworkError("response_too_large")
          return { status: 200, headers: { "content-type": "text/html; charset=utf-8" }, body }
        },
      }),
    })
    const response = await handler(request({ url: `https://www.freelancer.com/projects/${path}.html` }))
    expect(response.status).toBe(200)
    const result = await response.json()
    expect(result.title).toBe(title)
    expect(result.sourceUrl).toBe(`https://www.freelancer.com/projects/${path}`)
    expect(result.description.length).toBeGreaterThan(30)
    expect(result.description).not.toContain("Unrelated bidder proposal")
  })

  it("returns an actionable error for an unavailable Freelancer project", async () => {
    const handler = createExtractHandler({
      fetchPage: (url) => fetchPublicPage(url, {
        resolve: async () => [{ address: "93.184.216.34", family: 4 }],
        request: async () => ({ status: 404, headers: { "content-type": "text/html" }, body: "Not found" }),
      }),
    })
    const response = await handler(request({ url: "https://www.freelancer.com/projects/n8n/deleted" }))
    expect(response.status).toBe(502)
    await expect(response.json()).resolves.toEqual({ error: "fetch_failed" })
  })

  it("does not treat a Freelancer error shell as a task", async () => {
    const handler = createExtractHandler({
      fetchPage: async () => ({
        finalUrl: "https://www.freelancer.com/projects/n8n/deleted",
        contentType: "text/html",
        body: "<h1>Project unavailable</h1><p>This project is no longer available. Browse other projects or sign in to continue.</p>",
      }),
    })
    const response = await handler(request({ url: "https://www.freelancer.com/projects/n8n/deleted" }))
    expect(response.status).toBe(422)
    await expect(response.json()).resolves.toEqual({ error: "extraction_insufficient" })
  })

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
