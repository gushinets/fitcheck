// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest"
import OpenAI from "openai"
import { createOpenAISkillSuggestionTransport } from "./openai"

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

const request = {
  specialization: "Backend Developer",
  locale: "en" as const,
}

describe("OpenAI skill suggestion transport", () => {
  it("sends a JSON chat completion through the direct OpenAI API", async () => {
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
            model: "gpt-6-luna",
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

    const transport = createOpenAISkillSuggestionTransport({
      apiKey: "test-openai-key",
    })
    const result = await transport(request)

    expect(requestedUrl).toBe("https://api.openai.com/v1/chat/completions")
    expect(requestedBody).toMatchObject({
      model: "gpt-6-luna",
      max_completion_tokens: 500,
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
      reasoning_effort: "none",
    })
    expect(requestedBody).not.toHaveProperty("temperature")
    expect(requestedBody).not.toHaveProperty("thinking")
    expect(requestedBody).not.toHaveProperty("max_tokens")
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
            model: "gpt-6-luna",
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

    const transport = createOpenAISkillSuggestionTransport({
      apiKey: "test-openai-key",
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
    const transport = createOpenAISkillSuggestionTransport({
      apiKey: "test-openai-key",
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
    const transport = createOpenAISkillSuggestionTransport({
      apiKey: "test-openai-key",
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
    const transport = createOpenAISkillSuggestionTransport({
      apiKey: "test-openai-key",
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
            model: "gpt-6-luna",
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
    const transport = createOpenAISkillSuggestionTransport({
      apiKey: "test-openai-key",
    })

    await expect(transport(request)).rejects.toMatchObject({
      code: "invalid_output",
    })
  })
})

it('disables hidden SDK retries at outbound send', async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({error:{message:'private'}}),{status:500,headers:{'content-type':'application/json'}}))
  vi.stubGlobal('fetch',fetcher)
  await expect(createOpenAISkillSuggestionTransport({apiKey:'test-key'})(request)).rejects.toMatchObject({code:'upstream'})
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('records suggestion usage without awaiting an unavailable metrics sink', async () => {
  const { createWebsiteOperation } = await import('@/lib/metrics/operations')
  const operation = createWebsiteOperation({visitorId:'11111111-1111-4111-8111-111111111111',environment:'test',name:'suggestions'})
  const sink = {start:vi.fn(()=>new Promise<void>(()=>{})),finish:vi.fn().mockRejectedValue(new Error('private-collector-error'))}
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({
    id:'completion-skills',object:'chat.completion',created:0,model:'gpt-6-luna',
    choices:[{index:0,finish_reason:'stop',message:{role:'assistant',content:'{"skills":["Python"]}'}}],
    usage:{prompt_tokens:12,completion_tokens:4,prompt_tokens_details:{cached_tokens:3},completion_tokens_details:{reasoning_tokens:0}},
  }),{headers:{'content-type':'application/json'}})))
  await expect(createOpenAISkillSuggestionTransport({apiKey:'test-key',operation,attemptSink:sink})(request)).resolves.toEqual({skills:['Python']})
  expect(sink.start).toHaveBeenCalledWith(expect.objectContaining({provider:'openai',model:'gpt-6-luna',purpose:'skills.generate',ordinal:1,operationId:operation.operationId}))
  expect(sink.finish).toHaveBeenCalledWith(expect.objectContaining({provider:'openai',model:'gpt-6-luna',state:'succeeded',inputTokens:12,outputTokens:4,cachedInputTokens:3,reasoningTokens:0,cost:null,costBasis:'unknown'}))
})
