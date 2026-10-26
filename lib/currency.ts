import { z } from "zod"
import type { Currency } from "@/lib/types"

export const currencies = ["USD", "EUR", "RUB"] as const
export const currencySchema = z.enum(currencies)

export function formatRateRange(min?: number, max?: number) {
  if (min !== undefined && max !== undefined) return `${min}–${max}`
  if (min !== undefined) return `${min}+`
  if (max !== undefined) return `≤${max}`
  return ""
}

export function formatMoney(amount: number | string, currency?: Currency, unspecified = "currency unspecified") {
  return `${amount} ${currency ?? unspecified}`
}
