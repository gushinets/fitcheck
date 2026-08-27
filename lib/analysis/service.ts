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
  const prompt = buildAnalysisPrompt(request)
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const raw = await transport(request, prompt)
      const parsed = fitAnalysisSchema.safeParse(raw)
      if (parsed.success) return normalizeAnalysis(parsed.data)
      if (attempt === 1) {
        throw new AnalysisServiceError(
          "invalid_output",
          "Model output failed validation",
        )
      }
    } catch (error) {
      const retryable =
        error instanceof AnalysisServiceError && error.code === "invalid_output"
      if (!retryable || attempt === 1) throw error
    }
  }
  throw new AnalysisServiceError("invalid_output", "Model output failed validation")
}
