import type { AnalysisRequest, FitAnalysis } from "@/lib/types"
import { fitAnalysisSchema } from "./schema"
import { normalizeAnalysis } from "./normalize"
import { buildAnalysisPrompt, type AnalysisPrompt } from "./prompt"

export type AnalysisErrorCode =
  | "rate_limit"
  | "timeout"
  | "invalid_output"
  | "upstream"

export class AnalysisServiceError extends Error {
  constructor(
    public readonly code: AnalysisErrorCode,
    message: string,
  ) {
    super(message)
    this.name = "AnalysisServiceError"
  }
}

export type AnalysisTransport = (
  request: AnalysisRequest,
  prompt: AnalysisPrompt,
) => Promise<unknown>

export async function analyzeJob(
  request: AnalysisRequest,
  transport: AnalysisTransport,
): Promise<FitAnalysis> {
  const raw = await transport(request, buildAnalysisPrompt(request))
  const parsed = fitAnalysisSchema.safeParse(raw)
  if (!parsed.success) {
    throw new AnalysisServiceError("invalid_output", "Model output failed validation")
  }
  return normalizeAnalysis(parsed.data)
}
