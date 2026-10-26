// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest"
import type OpenAI from "openai"

const sdk = vi.hoisted(() => ({
  options: [] as { fetch: typeof fetch; maxRetries: number; timeout: number; baseURL: string; logLevel: string }[],
  mode: "normal",
}))
// Fault injection: simulate a future SDK unexpectedly sending twice or changing
// destination. The transport suites separately exercise the installed real SDK.
vi.mock("openai", () => ({default: class {
  chat: {completions: {create: () => Promise<Response>}}
  constructor(options: typeof sdk.options[number]) {
    sdk.options.push(options)
    this.chat = {completions: {create: async () => {
      const url = sdk.mode === "normal" || sdk.mode === "twice"
        ? "https://api.openai.com/v1/chat/completions" : sdk.mode
      const first = await options.fetch(url, {method:"POST"})
      return sdk.mode === "twice" ? options.fetch(url, {method:"POST"}) : first
    }}}
  }
}}))
import { createOpenAISender } from "./client"
const params: OpenAI.Chat.Completions.ChatCompletionCreateParamsNonStreaming = {model:"gpt-6-luna",messages:[]}
afterEach(() => { vi.unstubAllGlobals(); sdk.options.length=0; sdk.mode="normal" })

it("rejects an unexpected second SDK send before physical HTTP", async () => {
  const physical = vi.fn(async()=>new Response("{}"))
  vi.stubGlobal("fetch",physical)
  sdk.mode="twice"
  await expect(createOpenAISender("test-key")(params)).rejects.toThrow("OpenAI request boundary rejected")
  expect(physical).toHaveBeenCalledTimes(1)
})

it.each([
  "http://api.openai.com/v1/chat/completions",
  "https://api.openai.com:444/v1/chat/completions",
  "https://api.openai.com/v1/chat/completions?redirect=1",
  "https://user@api.openai.com/v1/chat/completions",
  "https://api.openai.com/v1/responses",
  "https://other.example/v1/chat/completions",
])("rejects altered SDK destination %s before physical HTTP", async url => {
  const physical = vi.fn()
  vi.stubGlobal("fetch",physical)
  sdk.mode=url
  await expect(createOpenAISender("test-key")(params)).rejects.toThrow("OpenAI request boundary rejected")
  expect(physical).not.toHaveBeenCalled()
})

it("concurrent physical attempts have independent send guards and explicit SDK limits", async () => {
  const physical = vi.fn(async()=>new Response("{}"))
  vi.stubGlobal("fetch",physical)
  const send = createOpenAISender("test-key")
  await Promise.all([send(params),send(params)])
  expect(physical).toHaveBeenCalledTimes(2)
  expect(sdk.options).toHaveLength(2)
  for (const options of sdk.options) {
    expect(options).toMatchObject({baseURL:"https://api.openai.com/v1",maxRetries:0,timeout:45_000,logLevel:"off"})
  }
})
