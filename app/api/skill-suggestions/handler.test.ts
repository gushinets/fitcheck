// @vitest-environment node

import { describe, expect, it } from "vitest"
import {
  SkillSuggestionServiceError,
  type SkillSuggestionTransport,
} from "@/lib/skill-suggestions/service"
import { createSkillSuggestionsHandler } from "./handler"

const allowedOrigin = "https://fitcheck.example.com"
const validBody = {
  specialization: "Backend Developer",
  locale: "en",
}

const transport: SkillSuggestionTransport = async () => ({
  skills: ["Python", "FastAPI"],
})

function request(body: unknown, origin = allowedOrigin) {
  return new Request("http://localhost:3000/api/skill-suggestions", {
    method: "POST",
    headers: { "content-type": "application/json", origin },
    body: typeof body === "string" ? body : JSON.stringify(body),
  })
}

describe("POST /api/skill-suggestions", () => {
  it("rejects an origin outside the allowlist", async () => {
    const handler = createSkillSuggestionsHandler({
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
    const handler = createSkillSuggestionsHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const response = await handler(request(validBody, "http://localhost:3000"))

    expect(response.status).toBe(200)
  })

  it("rejects malformed JSON and schema-invalid input", async () => {
    const handler = createSkillSuggestionsHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const malformedJson = await handler(request("{"))
    const invalidSchema = await handler(
      request({ ...validBody, specialization: "" }),
    )

    expect(malformedJson.status).toBe(400)
    await expect(malformedJson.json()).resolves.toEqual({
      error: "invalid_request",
    })
    expect(invalidSchema.status).toBe(400)
    await expect(invalidSchema.json()).resolves.toEqual({
      error: "invalid_request",
    })
  })

  it("rejects a body larger than 5,000 characters", async () => {
    const handler = createSkillSuggestionsHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const response = await handler(request("x".repeat(5_001)))

    expect(response.status).toBe(413)
    await expect(response.json()).resolves.toEqual({ error: "request_too_large" })
  })

  it("returns validated suggestions and a matched CORS origin", async () => {
    const handler = createSkillSuggestionsHandler({
      allowedOrigins: [allowedOrigin],
      transport,
    })

    const response = await handler(request(validBody))

    expect(response.status).toBe(200)
    expect(response.headers.get("access-control-allow-origin")).toBe(allowedOrigin)
    await expect(response.json()).resolves.toEqual({
      skills: ["Python", "FastAPI"],
    })
  })

  it.each([
    ["rate_limit", 429, "suggestions_rate_limit"],
    ["timeout", 504, "suggestions_timeout"],
    ["invalid_output", 502, "suggestions_invalid_output"],
    ["upstream", 502, "suggestions_upstream"],
  ] as const)("maps %s provider failures to %i", async (code, status, error) => {
    const handler = createSkillSuggestionsHandler({
      allowedOrigins: [allowedOrigin],
      transport: async () => {
        throw new SkillSuggestionServiceError(code, "provider failure")
      },
    })

    const response = await handler(request(validBody))

    expect(response.status).toBe(status)
    await expect(response.json()).resolves.toEqual({ error })
  })
})
