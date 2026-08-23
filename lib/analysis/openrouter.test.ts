// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import { goAnalysis } from "@/lib/mock-data"
import { createOpenRouterTransport } from "./openrouter"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("OpenRouter analysis transport", () => {
  it("sends a structured chat completion through the OpenRouter API", async () => {
    let requestedUrl = ""
    let requestedBody: Record<string, unknown> = {}

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        requestedUrl = String(input)
        requestedBody = JSON.parse(String(init?.body))

        return new Response(
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
            output: [
              {
                type: "message",
                role: "assistant",
                content: [
                  {
                    type: "output_text",
                    text: JSON.stringify(goAnalysis),
                  },
                ],
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

    const transport = createOpenRouterTransport({
      apiKey: "test-openrouter-key",
      model: "openrouter/free",
    })
    const result = await transport({} as never, {
      instructions: "System instructions",
      input: "User input",
    }).catch(() => undefined)

    expect(requestedUrl).toBe(
      "https://openrouter.ai/api/v1/chat/completions",
    )
    expect(requestedBody).toMatchObject({
      model: "openrouter/free",
      messages: [
        { role: "system", content: "System instructions" },
        { role: "user", content: "User input" },
      ],
      response_format: {
        type: "json_schema",
        json_schema: {
          name: "fit_analysis",
          strict: true,
        },
      },
    })
    expect(result).toEqual(goAnalysis)
  })
})
