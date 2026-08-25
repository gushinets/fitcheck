// @vitest-environment node

import { describe, expect, it, vi } from "vitest"
import { goAnalysis } from "@/lib/mock-data"
import { createOpenRouterTransport } from "./openrouter"

describe("OpenRouter analysis transport", () => {
  it("sends a structured chat completion through the OpenRouter API", async () => {
    let requestedBody: Record<string, unknown> = {}
    const request = vi.fn(async (body: Record<string, unknown>) => {
      requestedBody = body
      return {
        status: 200,
        body: JSON.stringify({
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
        }),
      }
    })

    const transport = createOpenRouterTransport({
      apiKey: "test-openrouter-key",
      model: "openrouter/free",
      request,
    })
    const result = await transport({} as never, {
      instructions: "System instructions",
      input: "User input",
    }).catch(() => undefined)

    expect(request).toHaveBeenCalledOnce()
    expect(requestedBody).toMatchObject({
      model: "openrouter/free",
      max_tokens: 1200,
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
