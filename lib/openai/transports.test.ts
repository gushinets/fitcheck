// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest"
import OpenAI from "openai"
import { createOpenAITransport } from "@/lib/analysis/openai"
import { createOpenAISkillSuggestionTransport } from "@/lib/skill-suggestions/openai"
import { createWebsiteOperation } from "@/lib/metrics/operations"

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })
const factories = [
  (sink: import("@/lib/metrics/provider").ProviderAttemptSink) => {
    const operation = createWebsiteOperation({visitorId:"11111111-1111-4111-8111-111111111111",environment:"test",name:"analysis"})
    const transport = createOpenAITransport({apiKey:"private-test-key",operation,attemptSink:sink})
    return () => transport({} as never,{instructions:"private-profile",input:"private-task"})
  },
  (sink: import("@/lib/metrics/provider").ProviderAttemptSink) => {
    const operation = createWebsiteOperation({visitorId:"11111111-1111-4111-8111-111111111111",environment:"test",name:"suggestions"})
    const transport = createOpenAISkillSuggestionTransport({apiKey:"private-test-key",operation,attemptSink:sink})
    return () => transport({specialization:"private-profile",locale:"en"})
  },
]

it.each(factories)("maps errors safely with one physical send and sanitized sink/logs", async factory => {
  vi.stubEnv("OPENAI_LOG","debug")
  const logs = [vi.spyOn(console,"error"),vi.spyOn(console,"warn"),vi.spyOn(console,"info"),vi.spyOn(console,"debug"),vi.spyOn(console,"log")]
  const cases = [
    {status:429,code:"rate_limit",state:"failed"},
    {status:408,code:"timeout",state:"unknown"},
    {status:500,code:"upstream",state:"failed"},
    {status:302,code:"upstream",state:"failed"},
    {status:200,code:"invalid_output",state:"succeeded"},
  ]
  for (const {status,code,state} of cases) {
    const sink = {start:vi.fn(async()=>{}),finish:vi.fn(async()=>{})}
    const fetcher = vi.fn(async (_input: unknown, init?: RequestInit) => {
      expect(init?.redirect).toBe("error")
      return new Response(JSON.stringify(status === 200 ? {choices:[{message:{content:"private-not-json"}}]} : {error:{message:"private-provider-message private-test-key"}}),{status,headers:{"content-type":"application/json",location:"https://evil.example"}})
    })
    vi.stubGlobal("fetch",fetcher)
    await expect(factory(sink)()).rejects.toMatchObject({code,message:expect.not.stringContaining("private")})
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(sink.start).toHaveBeenCalledTimes(1)
    expect(sink.finish).toHaveBeenCalledWith(expect.objectContaining({provider:"openai",model:"gpt-6-luna",state}))
    expect(JSON.stringify([sink.start.mock.calls,sink.finish.mock.calls,...logs.map(log=>log.mock.calls)])).not.toContain("private")
  }
  const sink = {start:vi.fn(async()=>{}),finish:vi.fn(async()=>{})}
  const fetcher = vi.fn().mockRejectedValue(new OpenAI.APIConnectionTimeoutError())
  vi.stubGlobal("fetch",fetcher)
  await expect(factory(sink)()).rejects.toMatchObject({code:"timeout"})
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(sink.finish).toHaveBeenCalledWith(expect.objectContaining({state:"unknown",errorCode:"timeout"}))
})

it.each(["", "gpt-6.1-luna", "deepseek-v4-flash"])("factories reject unsupported models %s", model => {
  const fetcher = vi.fn()
  vi.stubGlobal("fetch",fetcher)
  expect(()=>createOpenAITransport({apiKey:"test-key",model})).toThrow("Unsupported OpenAI configuration")
  expect(()=>createOpenAISkillSuggestionTransport({apiKey:"test-key",model})).toThrow("Unsupported OpenAI configuration")
  expect(fetcher).not.toHaveBeenCalled()
})
