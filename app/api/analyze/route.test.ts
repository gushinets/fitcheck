// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import {
  AnalysisServiceError,
  type AnalysisTransport,
} from "@/lib/analysis/service"
import { createAnalyzeHandler } from "./handler"
import { POST } from "./route"

const allowedOrigin = "chrome-extension://fitcheck-test"
const validBody = {
  profile: defaultProfile,
  job: detectedJob,
  locale: "en",
  memory: [],
}

const transport: AnalysisTransport = async () => goAnalysis

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

function request(body: unknown, origin = allowedOrigin) {
  return new Request("http://localhost:3000/api/analyze", {
    method: "POST",
    headers: { "content-type": "application/json", origin },
    body: JSON.stringify(body),
  })
}

describe("POST /api/analyze", () => {
  it("rejects an origin outside the allowlist", async () => {
    const handler = createAnalyzeHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const response = await handler(request(validBody, "https://evil.example"))

    expect(response.status).toBe(403)
    await expect(response.json()).resolves.toEqual({
      error: "origin_not_allowed",
    })
  })

  it("accepts the website's own origin without a duplicate allowlist entry", async () => {
    const handler = createAnalyzeHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const response = await handler(request(validBody, "http://localhost:3000"))

    expect(response.status).toBe(200)
  })

  it("returns 400 for an invalid profile", async () => {
    const handler = createAnalyzeHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const response = await handler(
      request({ ...validBody, profile: { ...defaultProfile, skills: [] } }),
    )

    expect(response.status).toBe(400)
    await expect(response.json()).resolves.toEqual({ error: "invalid_request" })
  })

  it("returns a validated analysis and matched CORS origin", async () => {
    const handler = createAnalyzeHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const response = await handler(request(validBody))

    expect(response.status).toBe(200)
    expect(response.headers.get("access-control-allow-origin")).toBe(allowedOrigin)
    await expect(response.json()).resolves.toMatchObject({
      score: 82,
      status: "GO",
    })
  })

  it("maps provider rate limits to 429", async () => {
    const handler = createAnalyzeHandler({
      allowedOrigins: [allowedOrigin],
      transport: async () => {
        throw new AnalysisServiceError("rate_limit", "limited")
      },
    })

    const response = await handler(request(validBody))

    expect(response.status).toBe(429)
    await expect(response.json()).resolves.toEqual({ error: "analysis_rate_limit" })
  })

  it("uses the server-only OpenRouter configuration", async () => {
    vi.stubEnv("OPENROUTER_API_KEY", "test-openrouter-key")
    vi.stubEnv("OPENROUTER_MODEL", "openrouter/free")
    vi.stubEnv("OPENAI_API_KEY", "")
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            id: "generation-test",
            object: "chat.completion",
            created: 0,
            model: "test/free-model",
            choices: [
              {
                index: 0,
                finish_reason: "stop",
                message: {
                  role: "assistant",
                  content: JSON.stringify(goAnalysis),
                },
              },
            ],
            usage: {
              prompt_tokens: 1,
              completion_tokens: 1,
              total_tokens: 2,
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    )

    const response = await POST(request(validBody))

    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toMatchObject({
      score: 82,
      status: "GO",
    })
  })

  it("reports missing OpenRouter configuration instead of returning a mock", async () => {
    vi.stubEnv("OPENROUTER_API_KEY", "")

    const response = await POST(request(validBody))

    expect(response.status).toBe(503)
    await expect(response.json()).resolves.toEqual({
      error: "server_not_configured",
    })
  })
})
