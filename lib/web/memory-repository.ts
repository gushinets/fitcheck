import type {
  AnalysisFeedback,
  FreelancerProfile,
  Locale,
} from "@/lib/types"
import { derivePassword, verifyPassword } from "./password"
import { localAccountSchema, normalizeEmail, vacancyDraftSchema } from "./schemas"
import { LocalAuthError } from "./repository"
import type {
  LocalUser,
  StoredLocalUser,
  VacancyDraft,
  WebHistoryEntry,
  WebsiteRepository,
  WebsiteSnapshot,
} from "./types"

interface MemorySeed {
  users?: StoredLocalUser[]
  activeUserId?: string | null
}

const clone = <T,>(value: T): T => structuredClone(value)

export function createMemoryWebsiteRepository(
  seed: MemorySeed = {},
): WebsiteRepository {
  const users = new Map(seed.users?.map((user) => [user.id, clone(user)]))
  const profiles = new Map<string, FreelancerProfile>()
  const preferences = new Map<string, Locale>()
  const drafts = new Map<string, VacancyDraft>()
  const history = new Map<string, WebHistoryEntry>()
  let activeUserId = seed.activeUserId ?? null

  function safeUser(user: StoredLocalUser): LocalUser {
    return clone({
      id: user.id,
      name: user.name,
      email: user.email,
      createdAt: user.createdAt,
    })
  }

  function snapshot(): WebsiteSnapshot {
    const stored = activeUserId ? users.get(activeUserId) : undefined
    if (!stored) {
      return {
        user: null,
        profile: null,
        preferences: null,
        draft: null,
        history: [],
      }
    }
    const entries = [...history.values()]
      .filter((entry) => entry.userId === stored.id)
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
      .slice(0, 50)
    return clone({
      user: safeUser(stored),
      profile: profiles.get(stored.id) ?? null,
      preferences: preferences.has(stored.id)
        ? { userId: stored.id, locale: preferences.get(stored.id)! }
        : null,
      draft: drafts.get(stored.id) ?? null,
      history: entries,
    })
  }

  return {
    async createUser(input) {
      const parsed = localAccountSchema.parse(input)
      if ([...users.values()].some((user) => user.email === parsed.email)) {
        throw new LocalAuthError("duplicate_email")
      }
      const stored: StoredLocalUser = {
        id: crypto.randomUUID(),
        email: parsed.email,
        name: parsed.name,
        password: await derivePassword(parsed.password),
        createdAt: new Date().toISOString(),
      }
      users.set(stored.id, stored)
      activeUserId = stored.id
      return safeUser(stored)
    },
    async authenticate(email, password) {
      const stored = [...users.values()].find(
        (user) => user.email === normalizeEmail(email),
      )
      if (!stored) throw new LocalAuthError("unknown_email")
      if (!(await verifyPassword(password, stored.password))) {
        throw new LocalAuthError("incorrect_password")
      }
      activeUserId = stored.id
      return safeUser(stored)
    },
    async loadSnapshot() {
      return snapshot()
    },
    async signOut() {
      activeUserId = null
    },
    async saveLocale(userId: string, locale: Locale) {
      preferences.set(userId, locale)
    },
    async saveProfile(userId: string, profile: FreelancerProfile) {
      profiles.set(userId, clone(profile))
    },
    async saveDraft(userId: string, draft: VacancyDraft | null) {
      if (draft) drafts.set(userId, vacancyDraftSchema.parse(clone(draft)))
      else drafts.delete(userId)
    },
    async addHistory(entry: WebHistoryEntry) {
      history.set(entry.id, clone(entry))
      const expired = [...history.values()]
        .filter((candidate) => candidate.userId === entry.userId)
        .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
        .slice(50)
      for (const candidate of expired) history.delete(candidate.id)
    },
    async saveFeedback(
      userId: string,
      entryId: string,
      feedback: AnalysisFeedback,
    ) {
      const entry = history.get(entryId)
      if (entry?.userId === userId) {
        history.set(entryId, { ...entry, feedback: clone(feedback) })
      }
    },
    async clearHistory(userId: string) {
      for (const [entryId, entry] of history) {
        if (entry.userId === userId) history.delete(entryId)
      }
    },
    async deleteUser(userId: string) {
      users.delete(userId)
      profiles.delete(userId)
      preferences.delete(userId)
      drafts.delete(userId)
      for (const [entryId, entry] of history) {
        if (entry.userId === userId) history.delete(entryId)
      }
      if (activeUserId === userId) activeUserId = null
    },
  }
}
