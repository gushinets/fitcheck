import "fake-indexeddb/auto"
import { beforeEach, describe, expect, it } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import type { WebHistoryEntry } from "./types"
import { createWebsiteRepository } from "./repository"

describe("IndexedDB website repository", () => {
  let repository: ReturnType<typeof createWebsiteRepository>
  let databaseName: string

  beforeEach(() => {
    databaseName = `fitcheck-test-${crypto.randomUUID()}`
    repository = createWebsiteRepository(databaseName)
  })

  it.each(["USD", "EUR", "RUB"] as const)("preserves the hourly rate and %s currency after reopening", async (rateCurrency) => {
    const user = await repository.createUser({ name: "Nikita", email: "me@example.com", password: "password-123" })
    await repository.saveProfile(user.id, { ...defaultProfile, preferredRate: 25.5, rateCurrency })
    expect((await createWebsiteRepository(databaseName).loadSnapshot()).profile).toMatchObject({ preferredRate: 25.5, rateCurrency })
  })

  it("restores skill proficiency after reopening the repository", async () => {
    const user = await repository.createUser({ name: "Nikita", email: "me@example.com", password: "password-123" })
    await repository.saveProfile(user.id, { ...defaultProfile, skills: ["Make.com", "n8n"], skillLevels: { "make.com": "primary", n8n: "basic" } })
    const snapshot = await createWebsiteRepository(databaseName).loadSnapshot()
    expect(snapshot.profile?.skillLevels).toEqual({ "make.com": "primary", n8n: "basic" })
  })

  it("creates a user, restores the session, and authenticates after sign out", async () => {
    const user = await repository.createUser({
      name: "Nikita",
      email: "ME@EXAMPLE.COM",
      password: "password-123",
    })

    expect((await repository.loadSnapshot()).user).toMatchObject({
      id: user.id,
      email: "me@example.com",
    })

    await repository.signOut()
    expect((await repository.loadSnapshot()).user).toBeNull()
    await expect(
      repository.authenticate("me@example.com", "password-123"),
    ).resolves.toMatchObject({ id: user.id })
  })

  it("isolates user-owned data", async () => {
    const first = await repository.createUser({
      name: "First",
      email: "first@example.com",
      password: "password-123",
    })
    await repository.saveProfile(first.id, defaultProfile)
    await repository.signOut()
    await repository.createUser({
      name: "Second",
      email: "second@example.com",
      password: "password-456",
    })

    expect((await repository.loadSnapshot()).profile).toBeNull()
  })

  it("loads legacy profiles with preference defaults", async () => {
    const user = await repository.createUser({
      name: "Nikita",
      email: "me@example.com",
      password: "password-123",
    })
    const legacyProfile = {
      specialization: "Backend Developer",
      skills: ["Python", "Django"],
      experienceYears: 5,
      preferredRate: 35,
      englishLevel: "Upper Intermediate",
    }

    await writeStoredProfile(databaseName, user.id, legacyProfile)

    expect((await repository.loadSnapshot()).profile).toEqual({
      ...legacyProfile,
      desiredMonthlyIncome: 0,
      workFormats: ["remote"],
    })
  })

  it("reports duplicate emails and incorrect passwords with typed codes", async () => {
    await repository.createUser({
      name: "First",
      email: "first@example.com",
      password: "password-123",
    })

    await expect(
      repository.createUser({
        name: "Again",
        email: "FIRST@example.com",
        password: "password-456",
      }),
    ).rejects.toMatchObject({ code: "duplicate_email" })

    await repository.signOut()
    await expect(
      repository.authenticate("first@example.com", "wrong-password"),
    ).rejects.toMatchObject({
      code: "incorrect_password",
    })
    await expect(
      repository.authenticate("missing@example.com", "password-123"),
    ).rejects.toMatchObject({ code: "unknown_email" })
  })

  it("persists locale, profile, draft, feedback, and a maximum of 50 history entries", async () => {
    const user = await repository.createUser({
      name: "Nikita",
      email: "me@example.com",
      password: "password-123",
    })
    await repository.saveLocale(user.id, "ru")
    await repository.saveProfile(user.id, defaultProfile)
    await repository.saveDraft(user.id, {
      id: "draft-1",
      sourceMode: "text",
      title: "Backend role",
      fixedBudget: 500,
      fixedBudgetMax: 750,
      budgetCurrency: "EUR",
      description: "Build production APIs for a growing SaaS product.",
      skills: ["Python"],
      updatedAt: "2026-08-25T12:00:00.000Z",
    })

    for (let index = 0; index < 51; index += 1) {
      await repository.addHistory(historyEntry(user.id, index))
    }
    await repository.saveFeedback(user.id, "entry-50", {
      correctedScore: 75,
      note: "Timezone matters",
      createdAt: "2026-08-25T13:00:00.000Z",
    })

    const reloaded = createWebsiteRepository(databaseName)
    const snapshot = await reloaded.loadSnapshot()
    expect(snapshot.preferences?.locale).toBe("ru")
    expect(snapshot.profile).toEqual(defaultProfile)
    expect(snapshot.draft?.title).toBe("Backend role")
    expect(snapshot.draft).toMatchObject({ fixedBudget: 500, fixedBudgetMax: 750, budgetCurrency: "EUR" })
    expect(snapshot.history).toHaveLength(50)
    expect(snapshot.history.map((entry) => entry.id)).not.toContain("entry-0")
    expect(snapshot.history[0]?.feedback?.correctedScore).toBe(75)
  })

  it("deletes only the selected local user and their data", async () => {
    const first = await repository.createUser({
      name: "First",
      email: "first@example.com",
      password: "password-123",
    })
    await repository.saveProfile(first.id, defaultProfile)
    await repository.signOut()
    const second = await repository.createUser({
      name: "Second",
      email: "second@example.com",
      password: "password-456",
    })
    await repository.deleteUser(second.id)

    expect((await repository.loadSnapshot()).user).toBeNull()
    await expect(
      repository.authenticate("first@example.com", "password-123"),
    ).resolves.toMatchObject({ id: first.id })
    expect((await repository.loadSnapshot()).profile).toEqual(defaultProfile)
  })
})

function historyEntry(userId: string, index: number): WebHistoryEntry {
  return {
    id: `entry-${index}`,
    userId,
    profile: defaultProfile,
    job: detectedJob,
    analysis: goAnalysis,
    createdAt: new Date(index * 1_000).toISOString(),
  }
}

function writeStoredProfile(
  databaseName: string,
  userId: string,
  profile: unknown,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName)
    request.onerror = () => reject(request.error)
    request.onsuccess = () => {
      const database = request.result
      const transaction = database.transaction("profiles", "readwrite")
      transaction.objectStore("profiles").put({ userId, profile })
      transaction.oncomplete = () => {
        database.close()
        resolve()
      }
      transaction.onerror = () => {
        database.close()
        reject(transaction.error)
      }
      transaction.onabort = () => {
        database.close()
        reject(transaction.error)
      }
    }
  })
}
