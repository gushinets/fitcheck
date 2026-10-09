export type FitStatus = "GO" | "NO_GO"

export type EnglishLevel =
  | "Basic"
  | "Intermediate"
  | "Upper Intermediate"
  | "Advanced"
  | "Fluent"

export type WorkFormat = "remote" | "office" | "hybrid"
export type SkillLevel = "primary" | "confident" | "basic"
export type Currency = "USD" | "EUR" | "RUB"

export interface FreelancerProfile {
  specialization: string
  skills: string[]
  /** Proficiency keyed by the trimmed, lower-case skill name. Omitted for legacy profiles. */
  skillLevels?: Record<string, SkillLevel>
  experienceYears: number
  preferredRate: number
  rateCurrency?: Currency
  desiredMonthlyIncome: number
  workFormats: WorkFormat[]
  englishLevel: EnglishLevel
}

export interface Job {
  id: string
  url?: string
  title: string
  description: string
  skills: string[]
  hourlyRateMin?: number
  hourlyRateMax?: number
  fixedBudget?: number
  /** Upper bound; fixedBudget is the lower bound when this is present. */
  fixedBudgetMax?: number
  budgetCurrency?: Currency
  experienceLevel?: string
  postedAgo?: string
  clientRating?: number
  clientSpend?: number
}

export interface FitBreakdown {
  skills: number
  experience: number
  rate: number
  english: number
  requirements: number
}

export interface FitAnalysis {
  score: number
  status: FitStatus
  label: string
  summary: string
  strengths: string[]
  risks: string[]
  breakdown: FitBreakdown
}

export type Locale = "en" | "ru"

export interface AnalysisFeedback {
  correctedScore: number
  note?: string
  createdAt: string
}

export interface CalibrationEntry {
  jobTitle: string
  predictedScore: number
  correctedScore?: number
  note?: string
}

export interface AnalysisRequest {
  profile: FreelancerProfile
  job: Job
  locale: Locale
  memory: CalibrationEntry[]
}

export interface HistoryEntry {
  id: string
  jobTitle: string
  score: number
  status: FitStatus
  timestamp: string
  createdAt: string
  analysis: FitAnalysis
  job: Job
  feedback?: AnalysisFeedback
}

/** Which section of the extension the user is viewing. */
export type Tab = "analyze" | "history" | "profile"

/**
 * The state of the "analyze" flow. Kept separate from navigation so the
 * primary decision is always the first thing rendered.
 */
export type AnalyzeState =
  | "ready"
  | "loading"
  | "result"
  | "details"
  | "feedback"
  | "unsupported"
  | "error"
