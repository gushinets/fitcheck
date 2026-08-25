import { analysisRequestSchema } from "@/lib/analysis/schema"
import {
  analyzeJob,
  AnalysisServiceError,
  type AnalysisTransport,
} from "@/lib/analysis/service"

const MAX_BODY_SIZE = 50_000

interface HandlerOptions {
  allowedOrigins: string[]
  transport: AnalysisTransport
}

export function corsHeaders(origin?: string) {
  return origin
    ? {
        "access-control-allow-origin": origin,
        "access-control-allow-methods": "POST, OPTIONS",
        "access-control-allow-headers": "content-type",
        vary: "Origin",
      }
    : undefined
}

export function json(
  body: unknown,
  status: number,
  allowedOrigin?: string,
) {
  return Response.json(body, {
    status,
    headers: corsHeaders(allowedOrigin),
  })
}

function errorResponse(error: unknown, origin: string) {
  if (error instanceof AnalysisServiceError) {
    const mapping = {
      rate_limit: [429, "analysis_rate_limit"],
      timeout: [504, "analysis_timeout"],
      invalid_output: [502, "analysis_invalid_output"],
      upstream: [502, "analysis_upstream"],
    } as const
    const [status, code] = mapping[error.code]
    return json({ error: code }, status, origin)
  }
  return json({ error: "analysis_upstream" }, 502, origin)
}

export function createAnalyzeHandler(options: HandlerOptions) {
  return async function handleAnalyze(request: Request) {
    const origin = request.headers.get("origin") ?? ""
    const requestOrigin = new URL(request.url).origin
    if (
      origin &&
      origin !== requestOrigin &&
      !options.allowedOrigins.includes(origin)
    ) {
      return json({ error: "origin_not_allowed" }, 403)
    }

    const declaredSize = Number(request.headers.get("content-length") ?? 0)
    if (declaredSize > MAX_BODY_SIZE) {
      return json({ error: "request_too_large" }, 413, origin)
    }

    let rawBody: string
    try {
      rawBody = await request.text()
    } catch {
      return json({ error: "invalid_request" }, 400, origin)
    }
    if (rawBody.length > MAX_BODY_SIZE) {
      return json({ error: "request_too_large" }, 413, origin)
    }

    let body: unknown
    try {
      body = JSON.parse(rawBody)
    } catch {
      return json({ error: "invalid_request" }, 400, origin)
    }

    const parsed = analysisRequestSchema.safeParse(body)
    if (!parsed.success) {
      return json({ error: "invalid_request" }, 400, origin)
    }

    try {
      const analysis = await analyzeJob(parsed.data, options.transport)
      return json(analysis, 200, origin)
    } catch (error) {
      return errorResponse(error, origin)
    }
  }
}
