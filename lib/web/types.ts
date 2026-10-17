import type {
  AnalysisFeedback,
  Currency,
  FitAnalysis,
  FreelancerProfile,
  Job,
  Locale,
} from "@/lib/types"

export interface PasswordDigest {
  salt: string
  hash: string
}

export interface LocalUser {
  id: string
  email: string
  name: string
  createdAt: string
}

export interface StoredLocalUser extends LocalUser {
  password: PasswordDigest
}

export interface LocalSession {
  userId: string
  createdAt: string
}

export interface UserPreferences {
  userId: string
  locale: Locale
}

export type VacancySourceMode = "url" | "text"

export interface VacancyDraft {
  id: string
  sourceMode: VacancySourceMode
  sourceUrl?: string
  rawSource?: string
  title: string
  description: string
  skills: string[]
  hourlyRateMin?: number
  hourlyRateMax?: number
  fixedBudget?: number
  fixedBudgetMax?: number
  budgetCurrency?: Currency
  updatedAt: string
}

export interface WebHistoryEntry {
  providerOperationId?: string
  id: string
  userId: string
  profile: FreelancerProfile
  job: Job
  analysis: FitAnalysis
  feedback?: AnalysisFeedback
  createdAt: string
}

export interface WebsiteSnapshot {
  user: LocalUser | null
  profile: FreelancerProfile | null
  preferences: UserPreferences | null
  draft: VacancyDraft | null
  history: WebHistoryEntry[]
}

export interface WebsiteRepository {
  exportLocalData(selectedUserId: string): Promise<import("./local-export").LocalImportRequest>
  createUser(input: {
    name: string
    email: string
    password: string
  }): Promise<LocalUser>
  authenticate(email: string, password: string): Promise<LocalUser>
  loadSnapshot(): Promise<WebsiteSnapshot>
  signOut(): Promise<void>
  saveLocale(userId: string, locale: Locale): Promise<void>
  saveProfile(userId: string, profile: FreelancerProfile): Promise<void>
  saveDraft(userId: string, draft: VacancyDraft | null): Promise<void>
  addHistory(entry: WebHistoryEntry): Promise<void>
  saveFeedback(
    userId: string,
    entryId: string,
    feedback: AnalysisFeedback,
  ): Promise<void>
  clearHistory(userId: string): Promise<void>
  deleteUser(userId: string): Promise<void>
}
