"use client"

import { History, Target, User } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Tab } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"

const items: { key: Tab; icon: typeof Target }[] = [
  { key: "analyze", icon: Target },
  { key: "history", icon: History },
  { key: "profile", icon: User },
]

interface BottomNavigationProps {
  active: Tab
  onChange: (tab: Tab) => void
  copy?: Messages
}

export function BottomNavigation({ active, onChange, copy = messages.en }: BottomNavigationProps) {
  return (
    <nav
      aria-label="Primary"
      className="grid grid-cols-3 border-t border-border bg-card"
    >
      {items.map(({ key, icon: Icon }) => {
        const isActive = active === key
        const localizedLabel = key === "analyze" ? copy.analyze : key === "history" ? copy.history : copy.profile
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors",
              isActive
                ? "text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-[18px]" aria-hidden="true" />
            {localizedLabel}
          </button>
        )
      })}
    </nav>
  )
}
