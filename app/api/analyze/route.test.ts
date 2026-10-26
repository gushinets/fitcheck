// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import {
  AnalysisServiceError,
  type AnalysisTransport,
} from "@/lib/analysis/service"
import { createAnalyzeHandler } from "./handler"

const allowedOrigin = "https://fitcheck.example.com"
const validBody = {
  profile: defaultProfile,
  job: detectedJob,
  locale: "en",
  memory: [],
}

const transport: AnalysisTransport = async () => ({ ...goAnalysis, strengths: [] })

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
  it.each(["primary", "confident", "basic"] as const)("passes %s proficiency through validation to the model", async (level) => {
    let modelEvidence = ""
    let modelLevel: unknown
    const handler = createAnalyzeHandler({
      allowedOrigins: [allowedOrigin],
      transport: async (input, prompt) => {
        modelLevel = input.profile.skillLevels?.n8n
        modelEvidence = prompt.input
        return { ...goAnalysis, strengths: [] }
      },
    })
    const response = await handler(request({
      ...validBody,
      profile: { ...defaultProfile, skills: ["n8n"], skillLevels: { n8n: level } },
    }))
    expect(response.status).toBe(200)
    expect(modelLevel).toBe(level)
    expect(modelEvidence).toContain(`n8n: ${level}`)
  })

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

})
