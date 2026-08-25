import { fitAnalysisSchema } from "@/lib/analysis/schema"
import {
  extractedVacancySchema,
  type ExtractedVacancy,
} from "@/lib/extraction/schema"
import type { AnalysisRequest, FitAnalysis } from "@/lib/types"
import { vacancyDraftSchema } from "./schemas"
import type { VacancyDraft } from "./types"

export type WebApiErrorCode =
  | "invalid_request"
  | "request_too_large"
  | "blocked_address"
  | "redirect_limit"
  | "unsupported_content"
  | "response_too_large"
  | "timeout"
  | "fetch_failed"
  | "extraction_insufficient"
  | "origin_not_allowed"
  | "server_not_configured"
  | "analysis_rate_limit"
  | "analysis_timeout"
  | "analysis_invalid_output"
  | "analysis_upstream"
  | "network_error"
  | "invalid_response"

export class WebApiError extends Error {
  constructor(public readonly code: WebApiErrorCode) {
    super(code)
    this.name = "WebApiError"
  }
}

export interface WebsiteApi {
  extractVacancy(url: string): Promise<VacancyDraft>
  analyzeVacancy(request: AnalysisRequest): Promise<FitAnalysis>
}

async function post(path: string, body: unknown) {
  try {
    return await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    })
  } catch {
    throw new WebApiError("network_error")
  }
}

async function errorFrom(response: Response): Promise<never> {
  const payload = await response.json().catch(() => null)
  const code =
    payload && typeof payload === "object" && "error" in payload
      ? String(payload.error)
      : "invalid_response"
  throw new WebApiError(code as WebApiErrorCode)
}

function toDraft(extracted: ExtractedVacancy): VacancyDraft {
  return vacancyDraftSchema.parse({
    ...extracted,
    id: crypto.randomUUID(),
    sourceMode: "url",
    updatedAt: new Date().toISOString(),
  })
}

export async function extractVacancy(url: string): Promise<VacancyDraft> {
  const response = await post("/api/extract", { url })
  if (!response.ok) return errorFrom(response)
  const payload = await response.json().catch(() => null)
  const parsed = extractedVacancySchema.safeParse(payload)
  if (!parsed.success) throw new WebApiError("invalid_response")
  return toDraft(parsed.data)
}

export async function analyzeVacancy(
  request: AnalysisRequest,
): Promise<FitAnalysis> {
  const response = await post("/api/analyze", request)
  if (!response.ok) return errorFrom(response)
  const payload = await response.json().catch(() => null)
  const parsed = fitAnalysisSchema.safeParse(payload)
  if (!parsed.success) throw new WebApiError("invalid_response")
  return parsed.data
}

export const websiteApi: WebsiteApi = { extractVacancy, analyzeVacancy }
