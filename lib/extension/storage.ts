import type {
  AnalysisFeedback,
  CalibrationEntry,
  FreelancerProfile,
  HistoryEntry,
} from "@/lib/types"

const STORAGE_KEY = "fitcheckState"
const STORAGE_VERSION = 1
const HISTORY_LIMIT = 50
const MEMORY_LIMIT = 10

export interface StorageArea {
  get(key: string): Promise<Record<string, unknown>>
  set(values: Record<string, unknown>): Promise<void>
}

export interface ExtensionState {
  version: number
  profile: FreelancerProfile | null
  history: HistoryEntry[]
}

function migrate(value: unknown): ExtensionState {
  if (!value || typeof value !== "object") {
    return { version: STORAGE_VERSION, profile: null, history: [] }
  }
  const candidate = value as Partial<ExtensionState>
  return {
    version: STORAGE_VERSION,
    profile: candidate.profile ?? null,
    history: Array.isArray(candidate.history)
      ? candidate.history.slice(0, HISTORY_LIMIT)
      : [],
  }
}

export function createExtensionStore(area: StorageArea) {
  async function load() {
    const values = await area.get(STORAGE_KEY)
    return migrate(values[STORAGE_KEY])
  }

  async function write(state: ExtensionState) {
    await area.set({
      [STORAGE_KEY]: {
        ...state,
        version: STORAGE_VERSION,
        history: state.history.slice(0, HISTORY_LIMIT),
      },
    })
  }

  return {
    load,
    async saveProfile(profile: FreelancerProfile) {
      await write({ ...(await load()), profile })
    },
    async resetProfile() {
      await write({ ...(await load()), profile: null })
    },
    async addAnalysis(entry: HistoryEntry) {
      const state = await load()
      await write({ ...state, history: [entry, ...state.history] })
    },
    async saveFeedback(entryId: string, feedback: AnalysisFeedback) {
      const state = await load()
      await write({
        ...state,
        history: state.history.map((entry) =>
          entry.id === entryId ? { ...entry, feedback } : entry,
        ),
      })
    },
    async clearHistory() {
      await write({ ...(await load()), history: [] })
    },
    async getCalibrationMemory(): Promise<CalibrationEntry[]> {
      const state = await load()
      return state.history.slice(0, MEMORY_LIMIT).map((entry) => ({
        jobTitle: entry.job.title,
        predictedScore: entry.analysis.score,
        ...(entry.feedback
          ? {
              correctedScore: entry.feedback.correctedScore,
              ...(entry.feedback.note ? { note: entry.feedback.note } : {}),
            }
          : {}),
      }))
    },
  }
}

export type ExtensionStore = ReturnType<typeof createExtensionStore>
