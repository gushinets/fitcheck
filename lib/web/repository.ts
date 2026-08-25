import {
  freelancerProfileSchema,
  normalizeFreelancerProfile,
} from "@/lib/analysis/schema"
import type {
  AnalysisFeedback,
  FreelancerProfile,
  Locale,
} from "@/lib/types"
import { derivePassword, verifyPassword } from "./password"
import { localAccountSchema, normalizeEmail, vacancyDraftSchema } from "./schemas"
import type {
  LocalSession,
  LocalUser,
  StoredLocalUser,
  VacancyDraft,
  WebHistoryEntry,
  WebsiteRepository,
  WebsiteSnapshot,
} from "./types"

const DEFAULT_DATABASE_NAME = "fitcheck-web"
const DATABASE_VERSION = 1
const HISTORY_LIMIT = 50
const ACTIVE_SESSION_KEY = "activeSession"

type AuthErrorCode =
  | "duplicate_email"
  | "unknown_email"
  | "incorrect_password"

interface StoredProfile {
  userId: string
  profile: unknown
}

interface StoredDraft {
  userId: string
  draft: VacancyDraft
}

interface MetaRecord {
  key: string
  value: LocalSession
}

export class LocalAuthError extends Error {
  constructor(public readonly code: AuthErrorCode) {
    super(code)
    this.name = "LocalAuthError"
  }
}

function publicUser(user: StoredLocalUser): LocalUser {
  return {
    id: user.id,
    name: user.name,
    email: user.email,
    createdAt: user.createdAt,
  }
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
    transaction.onabort = () => reject(transaction.error)
  })
}

function openDatabase(databaseName: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, DATABASE_VERSION)
    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = () => {
      const database = request.result
      const users = database.createObjectStore("users", { keyPath: "id" })
      users.createIndex("email", "email", { unique: true })
      database.createObjectStore("profiles", { keyPath: "userId" })
      database.createObjectStore("preferences", { keyPath: "userId" })
      database.createObjectStore("drafts", { keyPath: "userId" })
      const history = database.createObjectStore("history", { keyPath: "id" })
      history.createIndex("userId", "userId")
      database.createObjectStore("meta", { keyPath: "key" })
    }
  })
}

function emptySnapshot(): WebsiteSnapshot {
  return {
    user: null,
    profile: null,
    preferences: null,
    draft: null,
    history: [],
  }
}

function newestFirst(entries: WebHistoryEntry[]) {
  return entries.sort((left, right) =>
    right.createdAt.localeCompare(left.createdAt),
  )
}

export function createWebsiteRepository(
  databaseName = DEFAULT_DATABASE_NAME,
): WebsiteRepository {
  let databasePromise: Promise<IDBDatabase> | null = null
  const database = () => {
    databasePromise ??= openDatabase(databaseName)
    return databasePromise
  }

  return {
    async createUser(input) {
      const parsed = localAccountSchema.parse(input)
      const db = await database()
      const lookup = db.transaction("users", "readonly")
      const existing = await requestResult(
        lookup.objectStore("users").index("email").get(parsed.email),
      )
      await transactionDone(lookup)
      if (existing) throw new LocalAuthError("duplicate_email")

      const createdAt = new Date().toISOString()
      const stored: StoredLocalUser = {
        id: crypto.randomUUID(),
        name: parsed.name,
        email: parsed.email,
        password: await derivePassword(parsed.password),
        createdAt,
      }
      const session: LocalSession = { userId: stored.id, createdAt }
      const transaction = db.transaction(["users", "meta"], "readwrite")
      transaction.objectStore("users").add(stored)
      transaction.objectStore("meta").put({
        key: ACTIVE_SESSION_KEY,
        value: session,
      } satisfies MetaRecord)
      try {
        await transactionDone(transaction)
      } catch (error) {
        if ((error as DOMException | null)?.name === "ConstraintError") {
          throw new LocalAuthError("duplicate_email")
        }
        throw error
      }
      return publicUser(stored)
    },

    async authenticate(email, password) {
      const db = await database()
      const transaction = db.transaction("users", "readonly")
      const stored = (await requestResult(
        transaction
          .objectStore("users")
          .index("email")
          .get(normalizeEmail(email)),
      )) as StoredLocalUser | undefined
      await transactionDone(transaction)
      if (!stored) throw new LocalAuthError("unknown_email")
      if (!(await verifyPassword(password, stored.password))) {
        throw new LocalAuthError("incorrect_password")
      }

      const sessionTransaction = db.transaction("meta", "readwrite")
      sessionTransaction.objectStore("meta").put({
        key: ACTIVE_SESSION_KEY,
        value: {
          userId: stored.id,
          createdAt: new Date().toISOString(),
        },
      } satisfies MetaRecord)
      await transactionDone(sessionTransaction)
      return publicUser(stored)
    },

    async loadSnapshot() {
      const db = await database()
      const transaction = db.transaction(
        ["users", "profiles", "preferences", "drafts", "history", "meta"],
        "readonly",
      )
      const sessionRecord = (await requestResult(
        transaction.objectStore("meta").get(ACTIVE_SESSION_KEY),
      )) as MetaRecord | undefined
      if (!sessionRecord) {
        await transactionDone(transaction)
        return emptySnapshot()
      }

      const userId = sessionRecord.value.userId
      const [storedUser, storedProfile, preferences, storedDraft, history] =
        await Promise.all([
          requestResult(transaction.objectStore("users").get(userId)) as Promise<
            StoredLocalUser | undefined
          >,
          requestResult(
            transaction.objectStore("profiles").get(userId),
          ) as Promise<StoredProfile | undefined>,
          requestResult(
            transaction.objectStore("preferences").get(userId),
          ),
          requestResult(
            transaction.objectStore("drafts").get(userId),
          ) as Promise<StoredDraft | undefined>,
          requestResult(
            transaction.objectStore("history").index("userId").getAll(userId),
          ) as Promise<WebHistoryEntry[]>,
        ])
      await transactionDone(transaction)
      if (!storedUser) return emptySnapshot()

      return {
        user: publicUser(storedUser),
        profile: storedProfile
          ? normalizeFreelancerProfile(storedProfile.profile)
          : null,
        preferences: preferences ?? null,
        draft: storedDraft?.draft ?? null,
        history: newestFirst(history).slice(0, HISTORY_LIMIT),
      }
    },

    async signOut() {
      const db = await database()
      const transaction = db.transaction("meta", "readwrite")
      transaction.objectStore("meta").delete(ACTIVE_SESSION_KEY)
      await transactionDone(transaction)
    },

    async saveLocale(userId: string, locale: Locale) {
      const db = await database()
      const transaction = db.transaction("preferences", "readwrite")
      transaction.objectStore("preferences").put({ userId, locale })
      await transactionDone(transaction)
    },

    async saveProfile(userId: string, profile: FreelancerProfile) {
      const validProfile = freelancerProfileSchema.parse(profile)
      const db = await database()
      const transaction = db.transaction("profiles", "readwrite")
      transaction.objectStore("profiles").put({
        userId,
        profile: validProfile,
      } satisfies StoredProfile)
      await transactionDone(transaction)
    },

    async saveDraft(userId: string, draft: VacancyDraft | null) {
      const db = await database()
      const transaction = db.transaction("drafts", "readwrite")
      if (draft) {
        transaction.objectStore("drafts").put({
          userId,
          draft: vacancyDraftSchema.parse(draft),
        } satisfies StoredDraft)
      } else {
        transaction.objectStore("drafts").delete(userId)
      }
      await transactionDone(transaction)
    },

    async addHistory(entry: WebHistoryEntry) {
      const db = await database()
      const transaction = db.transaction("history", "readwrite")
      const store = transaction.objectStore("history")
      store.put(entry)
      const entries = (await requestResult(
        store.index("userId").getAll(entry.userId),
      )) as WebHistoryEntry[]
      for (const expired of newestFirst(entries).slice(HISTORY_LIMIT)) {
        store.delete(expired.id)
      }
      await transactionDone(transaction)
    },

    async saveFeedback(
      userId: string,
      entryId: string,
      feedback: AnalysisFeedback,
    ) {
      const db = await database()
      const transaction = db.transaction("history", "readwrite")
      const store = transaction.objectStore("history")
      const entry = (await requestResult(
        store.get(entryId),
      )) as WebHistoryEntry | undefined
      if (entry?.userId === userId) store.put({ ...entry, feedback })
      await transactionDone(transaction)
    },

    async clearHistory(userId: string) {
      const db = await database()
      const transaction = db.transaction("history", "readwrite")
      const store = transaction.objectStore("history")
      const keys = await requestResult(store.index("userId").getAllKeys(userId))
      for (const key of keys) store.delete(key)
      await transactionDone(transaction)
    },

    async deleteUser(userId: string) {
      const db = await database()
      const transaction = db.transaction(
        ["users", "profiles", "preferences", "drafts", "history", "meta"],
        "readwrite",
      )
      transaction.objectStore("users").delete(userId)
      transaction.objectStore("profiles").delete(userId)
      transaction.objectStore("preferences").delete(userId)
      transaction.objectStore("drafts").delete(userId)
      const history = transaction.objectStore("history")
      const keys = await requestResult(history.index("userId").getAllKeys(userId))
      for (const key of keys) history.delete(key)
      const meta = transaction.objectStore("meta")
      const session = (await requestResult(
        meta.get(ACTIVE_SESSION_KEY),
      )) as MetaRecord | undefined
      if (session?.value.userId === userId) meta.delete(ACTIVE_SESSION_KEY)
      await transactionDone(transaction)
    },
  }
}
