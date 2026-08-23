import type { Locale } from "@/lib/types"

export function resolveLocale(systemLocale?: string): Locale {
  return systemLocale?.toLowerCase().startsWith("ru") ? "ru" : "en"
}
