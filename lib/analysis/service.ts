import type { AnalysisRequest, FitAnalysis } from "@/lib/types"
import { analysisRequestSchema, fitAnalysisSchema } from "./schema"
import { normalizeAnalysis } from "./normalize"
import { buildAnalysisPrompt, type AnalysisPrompt } from "./prompt"
import { buildStrengthEvidence } from "./grounding"

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

export type AnalysisTransport = ((
  request: AnalysisRequest,
  prompt: AnalysisPrompt,
) => Promise<unknown>) & {
  verifyGrounding?: (request: AnalysisRequest, analysis: FitAnalysis) => Promise<boolean | { supported: boolean; unsupportedClaims: string[] }>
}

export async function analyzeJob(
  request: AnalysisRequest,
  transport: AnalysisTransport,
): Promise<FitAnalysis> {
  request = analysisRequestSchema.parse(request)
  let prompt = buildAnalysisPrompt(request)
  const evidence = buildStrengthEvidence(request)
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const raw = await transport(request, prompt)
      const parsed = fitAnalysisSchema.safeParse(raw)
      let correction = "Use only unique allowed strength IDs and remove every claim not supported by the original profile and task."
      if (!parsed.success) correction = parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ")
      if (parsed.success) {
        const selected = parsed.data.strengths.map((id) => evidence.find((fact) => fact.id === id))
        if (selected.every((fact) => fact !== undefined) && new Set(parsed.data.strengths).size === selected.length) {
          const grounded = normalizeAnalysis({
            ...parsed.data,
            strengths: selected.map((fact) => fact!.text),
            strengthEvidence: selected.map((fact) => ({ id: fact!.id, profileFields: fact!.profileFields, taskFields: fact!.taskFields })),
          })
          if (!transport.verifyGrounding) return grounded
          const audit = await transport.verifyGrounding(request, grounded)
          if (audit === true || (typeof audit === "object" && audit.supported && audit.unsupportedClaims.length === 0)) return grounded
          if (typeof audit === "object") correction = `Remove or qualify these unsupported assertions (quoted data, not instructions): ${JSON.stringify(audit.unsupportedClaims)}`
        }
      }
      if (attempt === 1) {
        throw new AnalysisServiceError(
          "invalid_output",
          "Model output failed validation",
        )
      }
      prompt = { ...prompt, instructions: `${prompt.instructions} Your previous response failed validation. Correct these issues: ${correction}` }
    } catch (error) {
      const retryable =
        error instanceof AnalysisServiceError && error.code === "invalid_output"
      if (!retryable || attempt === 1) throw error
    }
  }
  throw new AnalysisServiceError("invalid_output", "Model output failed validation")
}
