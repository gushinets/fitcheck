import type {
  AnalysisRequest,
  CalibrationEntry,
  FitAnalysis,
  FreelancerProfile,
  Job,
} from "@/lib/types"
import type { VacancyDraft, WebHistoryEntry } from "./types"

export function draftToJob(draft: VacancyDraft): Job {
  return {
    id: draft.id,
    ...(draft.sourceUrl ? { url: draft.sourceUrl } : {}),
    title: draft.title,
    description: draft.description,
    skills: [...draft.skills],
    ...(draft.budgetCurrency ? { budgetCurrency: draft.budgetCurrency } : {}),
    ...(draft.hourlyRateMin === undefined
      ? {}
      : { hourlyRateMin: draft.hourlyRateMin }),
    ...(draft.hourlyRateMax === undefined
      ? {}
      : { hourlyRateMax: draft.hourlyRateMax }),
    ...(draft.fixedBudget === undefined
      ? {}
      : { fixedBudget: draft.fixedBudget }),
    ...(draft.fixedBudgetMax === undefined ? {} : { fixedBudgetMax: draft.fixedBudgetMax }),
  }
}

export function createHistoryEntry(input: {
  userId: string
  profile: FreelancerProfile
  job: Job
  analysis: FitAnalysis
  now?: Date
}): WebHistoryEntry {
  const now = input.now ?? new Date()
  return structuredClone({
    id: crypto.randomUUID(),
    userId: input.userId,
    profile: input.profile,
    job: input.job,
    analysis: input.analysis,
    createdAt: now.toISOString(),
  })
}

export function toCalibrationMemory(
  history: WebHistoryEntry[],
): CalibrationEntry[] {
  return [...history]
    .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
    .slice(0, 10)
    .map((entry) => ({
      jobTitle: entry.job.title,
      predictedScore: entry.analysis.score,
      ...(entry.feedback
        ? {
            correctedScore: entry.feedback.correctedScore,
            ...(entry.feedback.note ? { note: entry.feedback.note } : {}),
          }
        : {}),
    }))
}

export function createAnalysisRequest(input: {
  profile: FreelancerProfile
  draft: VacancyDraft
  locale: AnalysisRequest["locale"]
  history: WebHistoryEntry[]
}): AnalysisRequest {
  return {
    profile: input.profile,
    job: draftToJob(input.draft),
    locale: input.locale,
    memory: toCalibrationMemory(input.history),
  }
}
