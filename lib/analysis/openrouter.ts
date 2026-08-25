import { spawn } from "node:child_process"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import type { AnalysisTransport } from "./service"
import { AnalysisServiceError } from "./service"

const openRouterUrl = "https://openrouter.ai/api/v1/chat/completions"

type OpenRouterResponse = { status: number; body: string }
type OpenRouterRequest = (
  body: Record<string, unknown>,
) => Promise<OpenRouterResponse>

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

function providerHttpError(status: number, body: string) {
  let message = body.slice(0, 500)
  try {
    const parsed = JSON.parse(body) as {
      error?: string | { message?: string; type?: string }
    }
    message =
      typeof parsed.error === "string"
        ? parsed.error
        : (parsed.error?.message ?? message)
  } catch {
    // Keep the truncated response body when the provider did not return JSON.
  }
  return Object.assign(new Error(`${status} ${JSON.stringify(message)}`), {
    status,
  })
}

function createCurlRequest(apiKey: string): OpenRouterRequest {
  return async (body) => {
    if (!/^[\x21-\x7e]+$/.test(apiKey)) {
      throw new Error("OpenRouter API key contains unsupported characters")
    }
    const taskDirectory = await mkdtemp(join(tmpdir(), "fitcheck-openrouter-"))
    const configPath = join(taskDirectory, "curl.conf")
    const escapedApiKey = apiKey.replaceAll("\\", "\\\\").replaceAll('"', '\\"')
    await writeFile(
      configPath,
      `header = "Authorization: Bearer ${escapedApiKey}"\n`,
      { mode: 0o600 },
    )

    try {
      return await new Promise((resolve, reject) => {
        const child = spawn(
          "curl",
          [
            "--silent",
            "--show-error",
            "--max-time",
            "45",
            "--request",
            "POST",
            "--url",
            openRouterUrl,
            "--config",
            configPath,
            "--header",
            "Content-Type: application/json",
            "--data-binary",
            "@-",
            "--write-out",
            "\n%{http_code}",
          ],
          { stdio: ["pipe", "pipe", "pipe"] },
        )
        let stdout = ""
        let stderr = ""

        child.stdout.setEncoding("utf8")
        child.stderr.setEncoding("utf8")
        child.stdout.on("data", (chunk: string) => {
          stdout += chunk
        })
        child.stderr.on("data", (chunk: string) => {
          stderr += chunk
        })
        child.on("error", reject)
        child.on("close", (code) => {
          if (code !== 0) {
            const error = Object.assign(
              new Error(stderr.trim() || `curl exited with code ${code}`),
              { code: code === 28 ? "ETIMEDOUT" : `CURL_${code}` },
            )
            reject(error)
            return
          }
          const match = stdout.match(/\n(\d{3})$/)
          if (!match) {
            reject(
              new Error("OpenRouter response did not include an HTTP status"),
            )
            return
          }
          resolve({
            status: Number(match[1]),
            body: stdout.slice(0, -match[0].length),
          })
        })

        child.stdin.end(JSON.stringify(body))
      })
    } finally {
      await rm(taskDirectory, { recursive: true, force: true })
    }
  }
}

export function createOpenRouterTransport(options: {
  apiKey: string
  model?: string
  request?: OpenRouterRequest
}): AnalysisTransport {
  const model = options.model ?? "openrouter/free"
  const request = options.request ?? createCurlRequest(options.apiKey)

  return async (_request, prompt) => {
    try {
      const response = await request({
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
      if (response.status < 200 || response.status >= 300) {
        throw providerHttpError(response.status, response.body)
      }
      const completion = JSON.parse(response.body) as {
        choices?: Array<{ message?: { content?: string | null } }>
      }
      const output = completion.choices?.[0]?.message?.content
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
