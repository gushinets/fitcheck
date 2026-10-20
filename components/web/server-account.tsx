"use client"

import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { Locale } from "@/lib/types"
import type { ServerWebsite } from "@/lib/web/server"
import { serverErrorMessage } from "@/lib/web/server-errors"

export function VerifyAccount({ server, email, locale, onVerified, onSignOut }: { server: ServerWebsite; email: string; locale: Locale; onVerified: () => Promise<void>; onSignOut: () => Promise<void> }) {
  const ru = locale === "ru"
  const [token, setToken] = useState("")
  const [status, setStatus] = useState("")
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => {
    const value = new URLSearchParams(window.location.hash.slice(1)).get("token")
    if (value) { setToken(value); window.history.replaceState(null, "", window.location.pathname) }
    }, 0)
    return () => clearTimeout(timer)
  }, [])
  async function run(action: () => Promise<void>) {
    setBusy(true); setStatus("")
    try { await action() } catch (e) { setStatus(serverErrorMessage(e, locale)) } finally { setBusy(false) }
  }
  return <main className="mx-auto grid min-h-svh max-w-lg content-center gap-5 p-6">
    <h1 className="text-2xl font-semibold">{ru ? "Подтвердите email" : "Verify your email"}</h1>
    <p>{email}</p><p>{ru ? "Запросите письмо и вставьте код подтверждения из него." : "Request an email and paste its verification code."}</p>
    <Button disabled={busy} onClick={() => run(async () => { await server.requestVerification(email); setStatus(ru ? "Письмо запрошено. Проверьте почту." : "Email requested. Check your inbox.") })}>{ru ? "Отправить письмо" : "Send verification email"}</Button>
    <form className="grid gap-3" onSubmit={event => { event.preventDefault(); void run(async () => { await server.verifyEmail(token); await onVerified() }) }}>
      <Input aria-label={ru ? "Код подтверждения" : "Verification code"} autoComplete="one-time-code" required value={token} onChange={event => setToken(event.target.value)} />
      <Button type="submit" disabled={busy || !token.trim()}>{ru ? "Подтвердить" : "Verify"}</Button>
    </form>
    {status ? <p role="status">{status}</p> : null}
    <Button variant="outline" disabled={busy} onClick={() => run(onSignOut)}>{ru ? "Выйти" : "Sign out"}</Button>
  </main>
}

export function ServerAccountTools({ server, locale, refresh }: { server: ServerWebsite; locale: Locale; refresh: () => Promise<void> }) {
  const ru = locale === "ru"
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [status, setStatus] = useState("")
  const [busy, setBusy] = useState(false)
  async function run(action: () => Promise<string>) {
    setBusy(true); setStatus("")
    try {
      const message = await action()
      await refresh()
      setStatus(message)
    } catch (e) { setStatus(serverErrorMessage(e, locale)) } finally { setBusy(false) }
  }
  return <section className="mx-auto grid max-w-3xl gap-4 rounded-3xl border border-border bg-card p-6">
    {server.hasGuestClaim() ? <Button disabled={busy} onClick={() => run(async () => { await server.claimGuest(); return ru ? "Демо перенесено в аккаунт." : "Demo saved to your account." })}>{ru ? "Сохранить демо в аккаунт" : "Save demo to account"}</Button> : null}
    <h2 className="text-lg font-semibold">{ru ? "Перенести данные из этого браузера" : "Import data from this browser"}</h2>
    <p className="text-sm text-muted-foreground">{ru ? "Укажите email и пароль прежнего локального аккаунта. Серверные данные сохранятся; повторный импорт пропускает уже перенесённые записи." : "Enter your previous local account credentials. Existing server data is preserved; retries skip imported records."}</p>
    <form className="grid gap-3" onSubmit={event => { event.preventDefault(); void run(async () => {
      const report = await server.importLocal(email, password)
      setPassword("")
      return report ? (ru ? `Перенесено: ${report.importedCount}; пропущено: ${report.skippedCount}; конфликты: ${report.conflictCount}; некорректные: ${report.invalidCount}.` : `Imported: ${report.importedCount}; skipped: ${report.skippedCount}; conflicts: ${report.conflictCount}; invalid: ${report.invalidCount}.`) : ""
    }) }}>
      <Input type="email" required aria-label={ru ? "Email локального аккаунта" : "Local account email"} placeholder="Email" value={email} onChange={event => setEmail(event.target.value)} />
      <Input type="password" required aria-label={ru ? "Пароль локального аккаунта" : "Local account password"} autoComplete="off" value={password} onChange={event => setPassword(event.target.value)} />
      <Button type="submit" disabled={busy}>{busy ? (ru ? "Переносим…" : "Importing…") : (ru ? "Перенести / повторить" : "Import / retry")}</Button>
    </form>
    {status ? <p role="status">{status}</p> : null}
  </section>
}
