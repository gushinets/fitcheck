// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import { OPTIONS, POST } from "./route"

const allowedOrigin = "chrome-extension://fitcheck-test"
const validBody = {
  specialization: "Backend Developer",
  locale: "en",
}

function request(origin = allowedOrigin) {
  return new Request("http://localhost:3000/api/skill-suggestions", {
    method: "POST",
    headers: { "content-type": "application/json", origin },
    body: JSON.stringify(validBody),
  })
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe("POST /api/skill-suggestions route", () => {
  it("reports missing DeepSeek configuration without calling a provider", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "")
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)

    const response = await POST(request())

    expect(response.status).toBe(503)
    await expect(response.json()).resolves.toEqual({
      error: "server_not_configured",
    })
  })

  it("rejects a foreign origin before reporting missing DeepSeek configuration", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "")
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)

    const response = await POST(request("https://evil.example"))

    expect(response.status).toBe(403)
    await expect(response.json()).resolves.toEqual({
      error: "origin_not_allowed",
    })
  })

  it("uses the environment-selected DeepSeek model", async () => {
    let requestedBody: Record<string, unknown> = {}
    vi.stubEnv("DEEPSEEK_API_KEY", "test-deepseek-key")
    vi.stubEnv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
        requestedBody = JSON.parse(String(init?.body))
        return new Response(
          JSON.stringify({
            id: "generation-test",
            object: "chat.completion",
            created: 0,
            model: "deepseek-v4-flash",
            choices: [
              {
                index: 0,
                finish_reason: "stop",
                message: {
                  role: "assistant",
                  content: '{"skills":["Python","FastAPI"]}',
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
        )
      }),
    )

    const response = await POST(request())

    expect(response.status).toBe(200)
    expect(requestedBody).toMatchObject({ model: "deepseek-v4-flash" })
    await expect(response.json()).resolves.toEqual({
      skills: ["Python", "FastAPI"],
    })
  })
})

describe("OPTIONS /api/skill-suggestions", () => {
  it("allows the route's own origin without an allowlist entry", async () => {
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)
    const preflight = new Request("http://localhost:3000/api/skill-suggestions", {
      method: "OPTIONS",
      headers: { origin: "http://localhost:3000" },
    })

    const response = await OPTIONS(preflight)

    expect(response.status).toBe(204)
    expect(response.headers.get("access-control-allow-origin")).toBe(
      "http://localhost:3000",
    )
  })

  it("allows a configured origin with CORS headers", async () => {
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)
    const preflight = new Request("http://localhost:3000/api/skill-suggestions", {
      method: "OPTIONS",
      headers: { origin: allowedOrigin },
    })

    const response = await OPTIONS(preflight)

    expect(response.status).toBe(204)
    expect(response.headers.get("access-control-allow-origin")).toBe(allowedOrigin)
  })

  it("rejects an origin outside the configured allowlist", async () => {
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)
    const preflight = new Request("http://localhost:3000/api/skill-suggestions", {
      method: "OPTIONS",
      headers: { origin: "https://evil.example" },
    })

    const response = await OPTIONS(preflight)

    expect(response.status).toBe(403)
    await expect(response.json()).resolves.toEqual({
      error: "origin_not_allowed",
    })
  })
})
