import OpenAI from "openai"

const endpoint = "https://api.openai.com/v1/chat/completions"

export function isSupportedOpenAIModel(model: string | undefined): boolean {
  return model === undefined || model === "gpt-6-luna"
}

// A fresh guard belongs to each physical attempt, including concurrent attempts.
// SDK retries and fetch redirects must never create unaccounted provider calls.
export function createOpenAISender(apiKey: string) {
  return (params: OpenAI.Chat.Completions.ChatCompletionCreateParamsNonStreaming) => {
    let sent = false
    const client = new OpenAI({
      apiKey,
      baseURL: "https://api.openai.com/v1",
      timeout: 45_000,
      maxRetries: 0,
      logLevel: "off",
      fetch: async (input, init) => {
        if (sent || String(input) !== endpoint || init?.method !== "POST") {
          throw new Error("OpenAI request boundary rejected")
        }
        sent = true
        return fetch(input, { ...init, redirect: "error" })
      },
    })
    return client.chat.completions.create(params)
  }
}
