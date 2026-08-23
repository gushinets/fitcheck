import type { FitAnalysis } from "@/lib/types"

export function normalizeAnalysis(analysis: FitAnalysis): FitAnalysis {
  return {
    ...analysis,
    status: analysis.score >= 70 ? "GO" : "NO_GO",
  }
}
