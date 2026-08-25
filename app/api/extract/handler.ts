import { extractVacancyContent } from "@/lib/extraction/content"
import {
  ExtractionNetworkError,
  type PublicPageResponse,
} from "@/lib/extraction/network"
import { extractRequestSchema } from "@/lib/extraction/schema"

const MAX_BODY_SIZE = 5_000
const MIN_DESCRIPTION_LENGTH = 30

interface HandlerOptions {
  fetchPage(url: string): Promise<PublicPageResponse>
}

function json(body: unknown, status: number) {
  return Response.json(body, { status })
}

const networkStatuses = {
  invalid_url: 400,
  blocked_address: 403,
  unsupported_content: 415,
  response_too_large: 413,
  timeout: 504,
  redirect_limit: 502,
  fetch_failed: 502,
} as const

export function createExtractHandler(options: HandlerOptions) {
  return async function handleExtract(request: Request) {
    let rawBody: string
    try {
      rawBody = await request.text()
    } catch {
      return json({ error: "invalid_request" }, 400)
    }
    if (rawBody.length > MAX_BODY_SIZE) {
      return json({ error: "request_too_large" }, 413)
    }

    let body: unknown
    try {
      body = JSON.parse(rawBody)
    } catch {
      return json({ error: "invalid_request" }, 400)
    }
    const parsed = extractRequestSchema.safeParse(body)
    if (!parsed.success) return json({ error: "invalid_request" }, 400)

    try {
      const result = extractVacancyContent(await options.fetchPage(parsed.data.url))
      if (
        result.title.length < 2 ||
        result.description.length < MIN_DESCRIPTION_LENGTH
      ) {
        return json({ error: "extraction_insufficient" }, 422)
      }
      return json(result, 200)
    } catch (error) {
      if (error instanceof ExtractionNetworkError) {
        return json({ error: error.code }, networkStatuses[error.code])
      }
      return json({ error: "extraction_insufficient" }, 422)
    }
  }
}
