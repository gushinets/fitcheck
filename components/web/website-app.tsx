"use client"

import { useEffect, useRef, useState } from "react"
import type { Locale } from "@/lib/types"
import { resolveLocale } from "@/lib/i18n/locale"
import { getWebMessages } from "@/lib/i18n/web-messages"
import type { WebsiteApi } from "@/lib/web/api"
import { websiteApi } from "@/lib/web/api"
import { createWebsiteRepository, LocalAuthError } from "@/lib/web/repository"
import type { WebsiteRepository, WebsiteSnapshot } from "@/lib/web/types"
import { AppShell, type WebView } from "./app-shell"
import { AuthScreen } from "./auth-screen"
import { LanguageSwitch } from "./language-switch"

const emptySnapshot: WebsiteSnapshot = {
  user: null,
  profile: null,
  preferences: null,
  draft: null,
  history: [],
}

function initialLocale(): Locale {
  if (typeof window === "undefined") return "en"
  const stored = window.localStorage.getItem("fitcheck.locale")
  return stored === "ru" || stored === "en"
    ? stored
    : resolveLocale(window.navigator.language)
}

export function WebsiteApp({
  repository,
  api = websiteApi,
}: {
  repository?: WebsiteRepository
  api?: WebsiteApi
}) {
  const repositoryRef = useRef<WebsiteRepository | null>(null)
  if (!repositoryRef.current) {
    repositoryRef.current = repository ?? createWebsiteRepository()
  }
  const store = repositoryRef.current
  void api
  const [locale, setLocale] = useState<Locale>(initialLocale)
  const [snapshot, setSnapshot] = useState<WebsiteSnapshot>(emptySnapshot)
  const [initialized, setInitialized] = useState(false)
  const [busy, setBusy] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [view, setView] = useState<WebView>("analyze")
  const copy = getWebMessages(locale)

  useEffect(() => {
    let active = true
    store
      .loadSnapshot()
      .then((loaded) => {
        if (!active) return
        setSnapshot(loaded)
        if (loaded.preferences) setLocale(loaded.preferences.locale)
        if (!loaded.profile) setView("profile")
      })
      .finally(() => active && setInitialized(true))
    return () => {
      active = false
    }
  }, [store])

  async function refresh() {
    setSnapshot(await store.loadSnapshot())
  }

  async function createAccount(input: {
    name: string
    email: string
    password: string
  }) {
    setBusy(true)
    setAuthError(null)
    try {
      const user = await store.createUser(input)
      await store.saveLocale(user.id, locale)
      await refresh()
      setView("profile")
    } catch (error) {
      setAuthError(authErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  async function signIn(input: { email: string; password: string }) {
    setBusy(true)
    setAuthError(null)
    try {
      await store.authenticate(input.email, input.password)
      await refresh()
    } catch (error) {
      setAuthError(authErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  function authErrorMessage(error: unknown) {
    if (!(error instanceof LocalAuthError)) return copy.authError
    return {
      duplicate_email: copy.duplicateEmail,
      unknown_email: copy.unknownEmail,
      incorrect_password: copy.incorrectPassword,
    }[error.code]
  }

  async function changeLocale(nextLocale: Locale) {
    setLocale(nextLocale)
    window.localStorage.setItem("fitcheck.locale", nextLocale)
    if (snapshot.user) {
      await store.saveLocale(snapshot.user.id, nextLocale)
      await refresh()
    }
  }

  if (!initialized) {
    return <main className="grid min-h-svh place-items-center bg-secondary"><p role="status" className="text-sm text-muted-foreground">{copy.loading}</p></main>
  }

  if (!snapshot.user) {
    return (
      <div className="relative">
        <div className="absolute right-4 top-4 z-10"><LanguageSwitch locale={locale} onChange={changeLocale} /></div>
        <AuthScreen copy={copy} error={authError} busy={busy} onCreate={createAccount} onSignIn={signIn} />
      </div>
    )
  }

  return (
    <AppShell user={snapshot.user} locale={locale} copy={copy} activeView={view} onNavigate={setView} onLocaleChange={changeLocale} onSignOut={async () => { await store.signOut(); setSnapshot(emptySnapshot); setView("analyze") }}>
      <section className="rounded-3xl border border-border bg-card p-6 shadow-sm sm:p-10">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-primary">{copy.productName}</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">{copy.completeProfileTitle}</h1>
        <p className="mt-3 max-w-2xl text-muted-foreground">{copy.completeProfileDescription}</p>
      </section>
    </AppShell>
  )
}
