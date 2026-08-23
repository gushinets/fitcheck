import { browser } from "wxt/browser"
import { fitAnalysisSchema } from "@/lib/analysis/schema"
import { resolveLocale } from "@/lib/i18n/locale"
import type { ExtensionRuntime } from "./runtime"
import { createExtensionStore } from "./storage"
import type { ParseJobResult } from "@/lib/upwork/parser"
import type { UpworkContentMessage } from "@/lib/upwork/messages"

async function activeTab() {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true })
  return tab
}

export function createBrowserRuntime(apiBaseUrl: string): ExtensionRuntime {
  const store = createExtensionStore(browser.storage.local)

  return {
    async getLocale() {
      return resolveLocale(browser.i18n.getUILanguage())
    },
    loadState: store.load,
    async getCurrentJob() {
      const tab = await activeTab()
      if (!tab?.id || !tab.url?.includes("upwork.com/")) {
        return { ok: false, reason: "unsupported" }
      }
      try {
        return (await browser.tabs.sendMessage(
          tab.id,
          { type: "GET_CURRENT_JOB" } satisfies UpworkContentMessage,
        )) as ParseJobResult
      } catch {
        return { ok: false, reason: "unsupported" }
      }
    },
    async analyze(request) {
      const response = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/api/analyze`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      })
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string }
        throw new Error(body.error ?? `analysis_http_${response.status}`)
      }
      const parsed = fitAnalysisSchema.safeParse(await response.json())
      if (!parsed.success) throw new Error("analysis_invalid_output")
      return parsed.data
    },
    saveProfile: store.saveProfile,
    resetProfile: store.resetProfile,
    addAnalysis: store.addAnalysis,
    saveFeedback: store.saveFeedback,
    clearHistory: store.clearHistory,
    async applyToJob() {
      const tab = await activeTab()
      if (!tab?.id) return
      await browser.tabs.update(tab.id, { active: true })
      await browser.tabs.sendMessage(
        tab.id,
        { type: "SCROLL_TO_APPLY" } satisfies UpworkContentMessage,
      )
    },
    closePopup() {
      window.close()
    },
  }
}
