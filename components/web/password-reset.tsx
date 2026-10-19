"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { createServerWebsite } from "@/lib/web/server"
import { serverErrorMessage } from "@/lib/web/server-errors"
import type { Locale } from "@/lib/types"

export function PasswordReset() {
  const [server] = useState(createServerWebsite)
  const [locale, setLocale] = useState<Locale>("en")
  const [token, setToken] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState("")
  const ru = locale === "ru"
  useEffect(() => {
    const timer = setTimeout(() => {
    const stored = localStorage.getItem("fitcheck.locale")
    setLocale(stored === "en" || stored === "ru" ? stored : navigator.language.startsWith("ru") ? "ru" : "en")
    const value = new URLSearchParams(window.location.hash.slice(1)).get("token")
    if (value) { setToken(value); window.history.replaceState(null, "", window.location.pathname) }
    }, 0)
    return () => clearTimeout(timer)
  }, [])
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setStatus("")
    try {
      if (token) { await server.confirmPasswordReset(token, password); setPassword(""); setStatus(ru ? "Пароль изменён. Войдите снова." : "Password changed. Sign in again.") }
      else { await server.requestPasswordReset(email); setStatus(ru ? "Письмо запрошено. Проверьте почту." : "Email requested. Check your inbox.") }
    } catch (error) { setStatus(serverErrorMessage(error, locale)) } finally { setBusy(false) }
  }
  return <main className="mx-auto grid min-h-svh max-w-lg content-center gap-5 p-6">
    <h1 className="text-2xl font-semibold">{ru ? "Восстановление пароля" : "Reset password"}</h1>
    <form onSubmit={submit} className="grid gap-4">
      {token ? <Input aria-label={ru ? "Новый пароль" : "New password"} type="password" autoComplete="new-password" minLength={15} maxLength={128} required value={password} onChange={event => setPassword(event.target.value)} /> : <Input aria-label="Email" type="email" required value={email} onChange={event => setEmail(event.target.value)} />}
      <Button type="submit" disabled={busy}>{token ? (ru ? "Сохранить пароль" : "Save password") : (ru ? "Запросить письмо" : "Request email")}</Button>
    </form>
    {status ? <p role="status">{status}</p> : null}<Link className="text-primary underline" href="/">{ru ? "Войти в FitCheck" : "Sign in to FitCheck"}</Link>
  </main>
}
