// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import { OPTIONS, POST } from "./route"

const allowedOrigin = "https://fitcheck.example.com"
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
  it("reports missing OpenAI configuration without calling a provider", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "obsolete-key")
    vi.stubEnv("OPEN_AI_KEY", "")
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)

    const response = await POST(request())

    expect(response.status).toBe(503)
    await expect(response.json()).resolves.toEqual({
      error: "server_not_configured",
    })
  })

  it("rejects a foreign origin before reporting missing OpenAI configuration", async () => {
    vi.stubEnv("DEEPSEEK_API_KEY", "obsolete-key")
    vi.stubEnv("OPEN_AI_KEY", "")
    vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)

    const response = await POST(request("https://evil.example"))

    expect(response.status).toBe(403)
    await expect(response.json()).resolves.toEqual({
      error: "origin_not_allowed",
    })
  })

  it("uses the environment-selected OpenAI model", async () => {
    let requestedBody: Record<string, unknown> = {}
    vi.stubEnv("DEEPSEEK_API_KEY", "obsolete-key")
    vi.stubEnv("DEEPSEEK_MODEL", "obsolete-model")
    vi.stubEnv("OPEN_AI_KEY", "test-openai-key")
    vi.stubEnv("OPEN_AI_MODEL", "gpt-6-luna")
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
            model: "gpt-6-luna",
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
    expect(requestedBody).toMatchObject({ model: "gpt-6-luna" })
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

it.each(["", "gpt-6.1-luna", "deepseek-v4-flash", " gpt-6-luna", "gpt-6-luna "])("rejects unsupported model %s before HTTP", async model => {
  vi.stubEnv("OPEN_AI_KEY", "test-key")
  vi.stubEnv("OPEN_AI_MODEL", model)
  vi.stubEnv("ALLOWED_ORIGINS", allowedOrigin)
  const fetcher = vi.fn()
  vi.stubGlobal("fetch",fetcher)
  const response = await POST(request())
  expect(response.status).toBe(503)
  expect(await response.json()).toEqual({error:"server_not_configured"})
  expect(fetcher).not.toHaveBeenCalled()
})
