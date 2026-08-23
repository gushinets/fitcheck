export type FitStatus = "GO" | "NO_GO"

export type EnglishLevel =
  | "Basic"
  | "Intermediate"
  | "Upper Intermediate"
  | "Advanced"
  | "Fluent"

export interface FreelancerProfile {
  specialization: string
  skills: string[]
  experienceYears: number
  preferredRate: number
  englishLevel: EnglishLevel
}

export interface Job {
  id: string
  url: string
  title: string
  description: string
  skills: string[]
  hourlyRateMin?: number
  hourlyRateMax?: number
  fixedBudget?: number
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
