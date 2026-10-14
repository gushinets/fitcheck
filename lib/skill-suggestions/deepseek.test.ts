// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import OpenAI from "openai"
import { createDeepSeekSkillSuggestionTransport } from "./deepseek"

afterEach(() => {
  vi.unstubAllGlobals()
})

const request = {
  specialization: "Backend Developer",
  locale: "en" as const,
}

describe("DeepSeek skill suggestion transport", () => {
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
            model: "deepseek-v4-flash",
            choices: [
              {
                index: 0,
                finish_reason: "stop",
                logprobs: null,
                message: {
                  role: "assistant",
                  content: '{"skills":["Python","FastAPI"]}',
                  refusal: null,
                },
              },
            ],
            usage: {
              prompt_tokens: 1,
              completion_tokens: 1,
              total_tokens: 2,
              prompt_tokens_details: {
                cached_tokens: 0,
                audio_tokens: 0,
              },
              completion_tokens_details: {
                reasoning_tokens: 0,
                audio_tokens: 0,
                accepted_prediction_tokens: 0,
                rejected_prediction_tokens: 0,
              },
            },
            system_fingerprint: null,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        )
      }),
    )

    const transport = createDeepSeekSkillSuggestionTransport({
      apiKey: "test-deepseek-key",
    })
    const result = await transport(request)

    expect(requestedUrl).toBe("https://api.deepseek.com/chat/completions")
    expect(requestedBody).toMatchObject({
      model: "deepseek-v4-flash",
      max_tokens: 500,
      messages: [
        {
          role: "system",
          content: expect.stringMatching(
            /concise[\s\S]*English[\s\S]*conventional spelling[\s\S]*valid JSON/i,
          ),
        },
        {
          role: "user",
          content: expect.stringContaining("Backend Developer"),
        },
      ],
      response_format: { type: "json_object" },
      thinking: { type: "disabled" },
    })
    expect(result).toEqual({ skills: ["Python", "FastAPI"] })
  })

  it("requests Russian generic competencies for a Russian locale", async () => {
    let requestedBody: Record<string, unknown> = {}
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
                logprobs: null,
                message: {
                  role: "assistant",
                  content: '{"skills":[]}',
                  refusal: null,
                },
              },
            ],
            usage: {
              prompt_tokens: 1,
              completion_tokens: 1,
              total_tokens: 2,
            },
            system_fingerprint: null,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        )
      }),
    )

    const transport = createDeepSeekSkillSuggestionTransport({
      apiKey: "test-deepseek-key",
    })
    await transport({ specialization: "Бэкенд-разработчик", locale: "ru" })

    expect(requestedBody).toMatchObject({
      messages: [
        {
          role: "system",
          content: expect.stringMatching(/Russian[\s\S]*conventional spelling/i),
        },
        {
          role: "user",
          content: expect.stringContaining("Бэкенд-разработчик"),
        },
      ],
    })
  })

  it("maps an SDK connection timeout to the stable timeout error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new OpenAI.APIConnectionTimeoutError()),
    )
    const transport = createDeepSeekSkillSuggestionTransport({
      apiKey: "test-deepseek-key",
    })

    await expect(transport(request)).rejects.toMatchObject({ code: "timeout" })
  })

  it("maps provider rate limits to the stable rate-limit error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ error: { message: "Slow down" } }), {
          status: 429,
          headers: { "content-type": "application/json" },
        }),
      ),
    )
    const transport = createDeepSeekSkillSuggestionTransport({
      apiKey: "test-deepseek-key",
    })

    await expect(transport(request)).rejects.toMatchObject({
      code: "rate_limit",
    })
  })

  it("maps provider server failures to the stable upstream error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ error: { message: "Unavailable" } }), {
          status: 500,
          headers: { "content-type": "application/json" },
        }),
      ),
    )
    const transport = createDeepSeekSkillSuggestionTransport({
      apiKey: "test-deepseek-key",
    })

    await expect(transport(request)).rejects.toMatchObject({ code: "upstream" })
  })

  it("preserves invalid JSON as the stable invalid-output error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            id: "generation-test",
            object: "chat.completion",
            created: 0,
            model: "deepseek-v4-flash",
            choices: [
              {
                index: 0,
                finish_reason: "stop",
                logprobs: null,
                message: {
                  role: "assistant",
                  content: "not JSON",
                  refusal: null,
                },
              },
            ],
            usage: {
              prompt_tokens: 1,
              completion_tokens: 1,
              total_tokens: 2,
            },
            system_fingerprint: null,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    )
    const transport = createDeepSeekSkillSuggestionTransport({
      apiKey: "test-deepseek-key",
    })

    await expect(transport(request)).rejects.toMatchObject({
      code: "invalid_output",
    })
  })
})

it('disables hidden SDK retries at outbound send', async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({error:{message:'private'}}),{status:500,headers:{'content-type':'application/json'}}))
  vi.stubGlobal('fetch',fetcher)
  await expect(createDeepSeekSkillSuggestionTransport({apiKey:'test-key'})(request)).rejects.toMatchObject({code:'upstream'})
  expect(fetcher).toHaveBeenCalledTimes(1)
})
