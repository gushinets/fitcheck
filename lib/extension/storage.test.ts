import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import type { HistoryEntry } from "@/lib/types"
import { createExtensionStore, type StorageArea } from "./storage"

function memoryArea(): StorageArea {
  let values: Record<string, unknown> = {}
  return {
    async get(key) {
      return { [key]: values[key] }
    },
    async set(next) {
      values = { ...values, ...structuredClone(next) }
    },
  }
}

function makeEntry(index: number): HistoryEntry {
  return {
    id: String(index),
    jobTitle: `Job ${index}`,
    score: goAnalysis.score,
    status: goAnalysis.status,
    timestamp: `Entry ${index}`,
    createdAt: new Date(2026, 0, index + 1).toISOString(),
    analysis: goAnalysis,
    job: { ...detectedJob, id: `job-${index}`, title: `Job ${index}` },
  }
}

describe("extension storage", () => {
  it("keeps the newest fifty history entries", async () => {
    const store = createExtensionStore(memoryArea())

    for (let index = 0; index < 52; index += 1) {
      await store.addAnalysis(makeEntry(index))
    }

    const state = await store.load()
    expect(state.history).toHaveLength(50)
    expect(state.history[0].id).toBe("51")
    expect(state.history.at(-1)?.id).toBe("2")
  })

  it("returns only ten newest calibration entries", async () => {
    const store = createExtensionStore(memoryArea())
    for (let index = 0; index < 12; index += 1) {
      await store.addAnalysis(makeEntry(index))
    }

    const memory = await store.getCalibrationMemory()

    expect(memory).toHaveLength(10)
    expect(memory[0]).toEqual({
      jobTitle: "Job 11",
      predictedScore: 82,
    })
  })

  it("preserves history when resetting a profile", async () => {
    const store = createExtensionStore(memoryArea())
    await store.saveProfile(defaultProfile)
    await store.addAnalysis(makeEntry(1))

    await store.resetProfile()

    const state = await store.load()
    expect(state.profile).toBeNull()
    expect(state.history).toHaveLength(1)
  })

  it("adds saved feedback to calibration memory", async () => {
    const store = createExtensionStore(memoryArea())
    await store.addAnalysis(makeEntry(1))

    await store.saveFeedback("1", {
      correctedScore: 65,
      note: "Timezone overlap is a blocker",
      createdAt: "2026-08-23T12:00:00.000Z",
    })

    expect(await store.getCalibrationMemory()).toEqual([
      {
        jobTitle: "Job 1",
        predictedScore: 82,
        correctedScore: 65,
        note: "Timezone overlap is a blocker",
      },
    ])
  })
})
