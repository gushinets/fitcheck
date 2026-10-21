import type { Currency } from "@/lib/types"

export interface DescriptionFields {
  skills: string[]
  hourlyRateMin?: number
  hourlyRateMax?: number
  fixedBudget?: number
  fixedBudgetMax?: number
  budgetCurrency?: Currency
}

const knownSkills = ["n8n", "Make.com", "Google Sheets", "Shopify", "TypeScript", "JavaScript", "Python", "React", "PostgreSQL", "Docker", "C#", "ESP32", "LoRa", "Rhino", "Grasshopper", "Lead Generation", "LinkedIn", "WhatsApp", "API", "JSON", "Webhooks"]
const numberPattern = String.raw`\d+(?:[ ,\.\u00a0]\d{3})*(?:[.,]\d{1,2})?`
const currencyPattern = String.raw`[Uu][Ss][Dd]|[Ee][Uu][Rr]|[Rr][Uu][Bb]|[Рр][Уу][Бб]\.?|₽|€|\$|[A-Z]{3}\b`
const averageBidPattern = String.raw`(?:average\s+bid|avg\.?\s+bid|средн(?:ий|яя|ее)\s+(?:бид|ставка|предложение))`

function currency(value?: string): Currency | undefined {
  if (!value) return undefined
  if (/^(USD|\$)$/i.test(value)) return "USD"
  if (/^(EUR|€)$/i.test(value)) return "EUR"
  if (/^(RUB|₽|руб\.?)$/i.test(value)) return "RUB"
  return undefined
}

function amount(value: string) {
  let normalized = value.replace(/[ \u00a0]/g, "")
  if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(normalized)) normalized = normalized.replace(/,/g, "")
  else if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(normalized)) normalized = normalized.replace(/\./g, "").replace(",", ".")
  else if (normalized.includes(",")) normalized = normalized.replace(/\./g, "").replace(",", ".")
  return Number(normalized)
}

function moneyFields(text: string): Omit<DescriptionFields, "skills"> {
  const candidates: Omit<DescriptionFields, "skills">[] = []
  const lines = text.split(/\n/).map(line => line.trim()).filter(Boolean)
  const bidLabel = new RegExp(`^${averageBidPattern}\\s*:?$`, "i")
  const bidMention = new RegExp(averageBidPattern, "i")
  const bareMoney = new RegExp(`^(?:${currencyPattern})?\\s*${numberPattern}(?:\\s*[-–—]\\s*(?:${currencyPattern})?\\s*${numberPattern})?\\s*(?:${currencyPattern})?$`, "u")
  for (const [index, line] of lines.entries()) {
    // Manual input still previews budget locally; competition itself is resolved by the backend.
    const adjacentBid = bareMoney.test(line) && [lines[index - 1], lines[index + 1]].some(value => value !== undefined && bidLabel.test(value))
    if (bidMention.test(line) || adjacentBid || /client\s+spend|per\s+(?:month|year)|\/\s*(?:month|year)|в\s+месяц/i.test(line)) continue
    const labelled = /\bbudget\b|бюджет|\brate\b|\bhourly\b|ставка|оплата/i.test(line)
    const pattern = new RegExp(`(?<prefix>${currencyPattern})?\\s*(?<min>${numberPattern})(?:\\s*[-–—]\\s*(?<second>${currencyPattern})?\\s*(?<max>${numberPattern}))?\\s*(?<suffix>${currencyPattern})?`, "gu")
    for (const match of line.matchAll(pattern)) {
      const groups = match.groups!
      if (!labelled && line.replace(match[0], "").replace(/\/\s*(?:h|hr|hour|час)\b/gi, "").trim()) continue
      if (line.slice(0, match.index).trimEnd().endsWith("-")) continue
      const tokens = [groups.prefix, groups.second, groups.suffix].filter(Boolean)
      const currencies = tokens.map(currency)
      if ((!tokens.length && !labelled) || currencies.some((entry) => !entry || entry !== currencies[0])) continue
      const before = line.slice(0, match.index)
      if (!tokens.length && !/\bbudget\b|бюджет|\brate\b|\bhourly\b|ставка|оплата/i.test(before)) continue
      const min = amount(groups.min)
      const max = groups.max ? amount(groups.max) : min
      const hourly = /\bhourly\b|\brate\b|ставка|per\s+hour|\/\s*(?:h\b|hr\b|hour\b|час)|в\s+час/i.test(line)
      if (min < 0 || max < min || !Number.isFinite(max) || max > (hourly ? 100_000 : 100_000_000)) continue
      const currencyFields = currencies[0] ? { budgetCurrency: currencies[0] } : {}
      const minimumOnly = !groups.max && /(?:\bfrom|\bstarting\s+at|от)\s*$/i.test(before)
      const maximumOnly = !groups.max && /(?:\bup\s+to|до)\s*$/i.test(before)
      candidates.push(hourly
        ? { ...(!maximumOnly ? { hourlyRateMin: min } : {}), ...(!minimumOnly ? { hourlyRateMax: max } : {}), ...currencyFields }
        : { fixedBudget: min, ...(groups.max ? { fixedBudgetMax: max } : {}), ...currencyFields })
    }
  }
  const unique = [...new Map(candidates.map((entry) => [JSON.stringify(entry), entry])).values()]
  return unique.length === 1 ? unique[0] : {}
}

export function extractDescriptionFields(text: string): DescriptionFields {
  const explicitSkills = [...text.matchAll(/^[ \t]*(?:required\s+skills|skills(?:\s+required)?|навыки|стек|технологии)[ \t]*:[ \t]*(?:\n[ \t]*)?([^\n]+)/gim)]
    .flatMap((match) => match[1].split(/[,;|]/).map((skill) => skill.trim()).filter(Boolean))
  const mentionedSkills = knownSkills.filter((skill) => {
    const escaped = skill.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    return new RegExp(`(?<![\\p{L}\\p{N}])${escaped}(?![\\p{L}\\p{N}])`, "iu").test(text)
  })
  const skills = [...explicitSkills, ...mentionedSkills].filter((skill, index, all) => all.findIndex((entry) => entry.toLowerCase() === skill.toLowerCase()) === index).map((skill) => skill.slice(0, 80)).slice(0, 100)
  return { skills, ...moneyFields(text) }
}
