"use client"

import { useState } from "react"
import { LockKeyhole } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { WebMessages } from "@/lib/i18n/web-messages"

type AuthMode = "create" | "signIn"

export function AuthScreen({
  copy,
  error,
  busy,
  onCreate,
  onSignIn,
  serverAccount = false,
}: {
  copy: WebMessages
  error: string | null
  busy: boolean
  onCreate: (input: { name: string; email: string; password: string }) => void
  onSignIn: (input: { email: string; password: string }) => void
  serverAccount?: boolean
}) {
  const [mode, setMode] = useState<AuthMode>("create")
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (mode === "create") onCreate({ name: serverAccount ? email.split("@")[0] : name, email, password })
    else onSignIn({ email, password })
  }

  return (
    <main className="grid min-h-svh bg-secondary lg:grid-cols-[1.05fr_0.95fr]">
      <section className="hidden bg-primary p-12 text-primary-foreground lg:flex lg:flex-col lg:justify-between">
        <div className="text-xl font-bold">{copy.productName}</div>
        <div className="max-w-xl">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] opacity-70">
            {copy.aiAnalysisLabel}
          </p>
          <h1 className="mt-5 text-balance text-5xl font-semibold leading-tight">
            {copy.tagline}
          </h1>
        </div>
        <p className="max-w-md text-sm leading-6 opacity-75">
          {copy.resultFeatures}
        </p>
      </section>

      <section className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-md rounded-3xl border border-border bg-card p-6 shadow-xl shadow-black/5 sm:p-8">
          <div className="mb-7 lg:hidden">
            <div className="text-xl font-bold text-primary">{copy.productName}</div>
            <p className="mt-2 text-sm text-muted-foreground">{copy.tagline}</p>
          </div>
          <div className="mb-6 grid grid-cols-2 rounded-xl bg-secondary p-1">
            <button
              type="button"
              aria-label={copy.switchToCreate}
              onClick={() => setMode("create")}
              className={`rounded-lg px-3 py-2 text-sm font-medium ${mode === "create" ? "bg-card shadow-sm" : "text-muted-foreground"}`}
            >
              {copy.createAccount}
            </button>
            <button
              type="button"
              aria-label={copy.switchToSignIn}
              onClick={() => setMode("signIn")}
              className={`rounded-lg px-3 py-2 text-sm font-medium ${mode === "signIn" ? "bg-card shadow-sm" : "text-muted-foreground"}`}
            >
              {copy.signIn}
            </button>
          </div>

          <h2 className="text-2xl font-semibold">
            {mode === "create" ? copy.createAccountTitle : copy.signInTitle}
          </h2>
          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === "create" && !serverAccount ? (
              <div className="space-y-1.5">
                <Label htmlFor="auth-name">{copy.name}</Label>
                <Input id="auth-name" required value={name} onChange={(event) => setName(event.target.value)} />
              </div>
            ) : null}
            <div className="space-y-1.5">
              <Label htmlFor="auth-email">{copy.email}</Label>
              <Input id="auth-email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="auth-password">{copy.password}</Label>
              <Input id="auth-password" type="password" autoComplete={mode === "create" ? "new-password" : "current-password"} minLength={serverAccount && mode === "create" ? 15 : serverAccount ? 1 : 8} maxLength={serverAccount ? 128 : 200} required value={password} onChange={(event) => setPassword(event.target.value)} />
            </div>
            {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
            <Button type="submit" disabled={busy} className="h-11 w-full font-semibold">
              {mode === "create" ? copy.createAccount : copy.signIn}
            </Button>
          </form>
          {serverAccount ? <a className="mt-4 block text-sm text-primary underline" href="/auth/password-reset">{copy.passwordReset}</a> : null}
          <div className="mt-5 flex gap-3 rounded-xl bg-secondary p-3 text-xs leading-5 text-muted-foreground">
            <LockKeyhole className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p>{copy.localAccountNotice}</p>
          </div>
        </div>
      </section>
    </main>
  )
}
