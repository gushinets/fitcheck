import OpenAI from "openai"
import type { AnalysisTransport } from "./service"
import { AnalysisServiceError } from "./service"

const score = { type: "integer", minimum: 0, maximum: 100 } as const

const fitAnalysisJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    score,
    status: { type: "string", enum: ["GO", "NO_GO"] },
    label: { type: "string", minLength: 1, maxLength: 80 },
    summary: { type: "string", minLength: 1, maxLength: 800 },
    strengths: {
      type: "array",
      minItems: 3,
      maxItems: 3,
      items: { type: "string", minLength: 1, maxLength: 240 },
    },
    risks: {
      type: "array",
      maxItems: 3,
      items: { type: "string", minLength: 1, maxLength: 240 },
    },
    breakdown: {
      type: "object",
      additionalProperties: false,
      properties: {
        skills: score,
        experience: score,
        rate: score,
        english: score,
        requirements: score,
      },
      required: ["skills", "experience", "rate", "english", "requirements"],
    },
  },
  required: [
    "score",
    "status",
    "label",
    "summary",
    "strengths",
    "risks",
    "breakdown",
  ],
} as const

function mapProviderError(error: unknown): AnalysisServiceError {
  if (error instanceof AnalysisServiceError) return error
  const candidate = error as { status?: number; code?: string; name?: string }
  if (candidate.status === 429) {
    return new AnalysisServiceError("rate_limit", "OpenRouter rate limit reached")
  }
  if (
    candidate.code === "ETIMEDOUT" ||
    candidate.name === "AbortError" ||
    candidate.status === 408
  ) {
    return new AnalysisServiceError("timeout", "OpenRouter request timed out")
  }
  return new AnalysisServiceError("upstream", "OpenRouter request failed")
}

function logProviderError(error: unknown) {
  const candidate = error as {
    name?: string
    status?: number
    code?: string
    message?: string
    error?: { type?: string }
  }
  console.error("[fitcheck] OpenRouter request failed", {
    name: candidate.name,
    status: candidate.status,
    code: candidate.code,
    type: candidate.error?.type,
    message: candidate.message?.slice(0, 500),
  })
}

export function createOpenRouterTransport(options: {
  apiKey: string
  model?: string
}): AnalysisTransport {
  const client = new OpenAI({
    apiKey: options.apiKey,
    baseURL: "https://openrouter.ai/api/v1",
    timeout: 45_000,
  })
  const model = options.model ?? "openrouter/free"

  return async (_request, prompt) => {
    try {
      const response = await client.chat.completions.create({
        model,
        max_tokens: 1200,
        messages: [
          { role: "system", content: prompt.instructions },
          { role: "user", content: prompt.input },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: "fit_analysis",
            strict: true,
            schema: fitAnalysisJsonSchema,
          },
        },
      })
      const output = response.choices[0]?.message.content
      if (!output) {
        throw new AnalysisServiceError("invalid_output", "Model returned no output")
      }
      try {
        return JSON.parse(output)
      } catch {
        throw new AnalysisServiceError("invalid_output", "Model returned invalid JSON")
      }
    } catch (error) {
      logProviderError(error)
      throw mapProviderError(error)
    }
  }
}
