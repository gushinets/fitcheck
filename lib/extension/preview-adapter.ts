import { defaultProfile, detectedJob, goAnalysis, historySeed } from "@/lib/mock-data"
import { resolveLocale } from "@/lib/i18n/locale"
import type { ExtensionRuntime } from "./runtime"
import type { ExtensionState } from "./storage"

export function createPreviewRuntime(): ExtensionRuntime {
  let state: ExtensionState = { version: 1, profile: defaultProfile, history: historySeed }
  return {
    async getLocale() { return resolveLocale(globalThis.navigator?.language) },
    async loadState() { return structuredClone(state) },
    async getCurrentJob() { return { ok: true, job: detectedJob } },
    async analyze() { return goAnalysis },
    async saveProfile(profile) { state = { ...state, profile } },
    async resetProfile() { state = { ...state, profile: null } },
    async addAnalysis(entry) { state = { ...state, history: [entry, ...state.history].slice(0, 50) } },
    async saveFeedback(entryId, feedback) {
      state = { ...state, history: state.history.map((entry) => entry.id === entryId ? { ...entry, feedback } : entry) }
    },
    async clearHistory() { state = { ...state, history: [] } },
    async applyToJob() {},
    closePopup() {},
  }
}
