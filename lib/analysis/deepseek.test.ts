// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import OpenAI from "openai"
import { goAnalysis } from "@/lib/mock-data"
import { createDeepSeekTransport } from "./deepseek"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("DeepSeek analysis transport", () => {
  it("sends a JSON chat completion through the direct DeepSeek API", async () => {
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

    const transport = createDeepSeekTransport({
      apiKey: "test-deepseek-key",
    })
    const result = await transport({} as never, {
      instructions: "System instructions",
      input: "User input",
    })

    expect(requestedUrl).toBe(
      "https://api.deepseek.com/chat/completions",
    )
    expect(requestedBody).toMatchObject({
      model: "deepseek-v4-flash",
      max_tokens: 1200,
      messages: [
        {
          role: "system",
          content: expect.stringMatching(
            /System instructions[\s\S]*Return only valid JSON[\s\S]*"score"[\s\S]*"breakdown"/,
          ),
        },
        { role: "user", content: "User input" },
      ],
      response_format: {
        type: "json_object",
      },
    })
    expect(result).toEqual(goAnalysis)
  })

  it("maps an SDK connection timeout to the stable timeout error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new OpenAI.APIConnectionTimeoutError()),
    )
    const transport = createDeepSeekTransport({
      apiKey: "test-deepseek-key",
    })

    await expect(
      transport({} as never, {
        instructions: "System instructions",
        input: "User input",
      }),
    ).rejects.toMatchObject({ code: "timeout" })
  })
})
