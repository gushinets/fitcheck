import type { ParseJobResult } from "@/lib/upwork/parser"
import type {
  AnalysisFeedback,
  AnalysisRequest,
  FitAnalysis,
  FreelancerProfile,
  HistoryEntry,
  Locale,
} from "@/lib/types"
import type { ExtensionState } from "./storage"

export interface ExtensionRuntime {
  getLocale(): Promise<Locale>
  loadState(): Promise<ExtensionState>
  getCurrentJob(): Promise<ParseJobResult>
  analyze(request: AnalysisRequest): Promise<FitAnalysis>
  saveProfile(profile: FreelancerProfile): Promise<void>
  resetProfile(): Promise<void>
  addAnalysis(entry: HistoryEntry): Promise<void>
  saveFeedback(entryId: string, feedback: AnalysisFeedback): Promise<void>
  clearHistory(): Promise<void>
  applyToJob(): Promise<void>
  closePopup(): void
}
