"use client"

import type { ReactNode } from "react"
import { BriefcaseBusiness, History, LogOut, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Locale } from "@/lib/types"
import type { LocalUser } from "@/lib/web/types"
import type { WebMessages } from "@/lib/i18n/web-messages"
import { LanguageSwitch } from "./language-switch"

export type WebView = "analyze" | "history" | "profile"

export function AppShell({
  user,
  locale,
  copy,
  activeView,
  onNavigate,
  onLocaleChange,
  onSignOut,
  children,
}: {
  user: LocalUser
  locale: Locale
  copy: WebMessages
  activeView: WebView
  onNavigate: (view: WebView) => void
  onLocaleChange: (locale: Locale) => void
  onSignOut: () => void
  children: ReactNode
}) {
  const navigation = [
    { id: "analyze" as const, label: copy.newAnalysis, icon: BriefcaseBusiness },
    { id: "history" as const, label: copy.history, icon: History },
    { id: "profile" as const, label: copy.profile, icon: UserRound },
  ]

  return (
    <div className="min-h-svh bg-secondary/60">
      <header className="sticky top-0 z-20 border-b border-border bg-background/90 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <button type="button" onClick={() => onNavigate("analyze")} className="mr-auto text-lg font-bold tracking-tight text-primary">
            {copy.productName}
          </button>
          <nav aria-label={copy.primaryNavigation} className="hidden items-center gap-1 md:flex">
            {navigation.map(({ id, label, icon: Icon }) => (
              <button key={id} type="button" onClick={() => onNavigate(id)} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-secondary hover:text-foreground"}`}>
                <Icon className="size-4" aria-hidden="true" />{label}
              </button>
            ))}
          </nav>
          <LanguageSwitch locale={locale} onChange={onLocaleChange} />
          <div className="hidden text-sm font-medium sm:block">{user.name}</div>
          <Button variant="ghost" size="icon" aria-label={copy.signOut} onClick={onSignOut}>
            <LogOut className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-10">{children}</main>
      <nav aria-label={copy.primaryNavigation} className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-3 border-t border-border bg-background/95 p-2 backdrop-blur md:hidden">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => onNavigate(id)} className={`flex flex-col items-center gap-1 rounded-lg px-2 py-2 text-[11px] font-medium ${activeView === id ? "text-primary" : "text-muted-foreground"}`}>
            <Icon className="size-4" aria-hidden="true" />{label}
          </button>
        ))}
      </nav>
    </div>
  )
}
