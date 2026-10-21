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
  proposalCount?: number | null
  averageBid?: number | null
  averageBidCurrency?: Currency | null
  provenance?: Record<string, "json_ld" | "html" | "text">
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
  /** Decision threshold saved with the result; absent in legacy analyses. */
  verdictThreshold?: number
  status: FitStatus
  label: string
  summary: string
  strengths: string[]
  /** Server-verified profile and task sources, aligned with strengths. Absent in legacy reports. */
  strengthEvidence?: { id: string; profileFields: string[]; taskFields: string[] }[]
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
