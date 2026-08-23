import type { Job } from "@/lib/types"

export type ParseJobResult =
  | { ok: true; job: Job }
  | { ok: false; reason: "unsupported" | "incomplete" }

function text(element: Element | null) {
  return element?.textContent?.replace(/\s+/g, " ").trim() || undefined
}

function firstText(document: Document, selectors: string[]) {
  for (const selector of selectors) {
    const value = text(document.querySelector(selector))
    if (value) return value
  }
  return undefined
}

function structuredJob(document: Document) {
  for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const parsed = JSON.parse(node.textContent ?? "")
      const candidates = Array.isArray(parsed) ? parsed : [parsed]
      const job = candidates.find((candidate) => candidate?.["@type"] === "JobPosting")
      if (job) return job as Record<string, unknown>
    } catch {
      // Ignore malformed structured data and continue with semantic DOM data.
    }
  }
  return undefined
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() : undefined
}

function parseNumber(value: string) {
  const parsed = Number(value.replace(/,/g, ""))
  return Number.isFinite(parsed) ? parsed : undefined
}

function parseBudget(value?: string) {
  if (!value) return {}
  const amounts = [...value.matchAll(/\$\s*([\d,.]+)/g)]
    .map((match) => parseNumber(match[1]))
    .filter((amount): amount is number => amount !== undefined)

  if (/\/\s*hr|hourly|per hour/i.test(value)) {
    return {
      hourlyRateMin: amounts[0],
      hourlyRateMax: amounts[1] ?? amounts[0],
    }
  }
  if (/fixed/i.test(value)) return { fixedBudget: amounts[0] }
  return {}
}

function parseCompactMoney(value?: string) {
  if (!value) return undefined
  const match = value.match(/\$\s*([\d,.]+)\s*([km])?/i)
  if (!match) return undefined
  const amount = parseNumber(match[1])
  if (amount === undefined) return undefined
  const multiplier = match[2]?.toLowerCase() === "m" ? 1_000_000 : match[2] ? 1_000 : 1
  return amount * multiplier
}

function parseRating(value?: string) {
  if (!value) return undefined
  const rating = Number(value.match(/\d+(?:\.\d+)?/)?.[0])
  return Number.isFinite(rating) && rating >= 0 && rating <= 5 ? rating : undefined
}

function unique(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))]
}

function isSupportedUpworkJob(url: URL) {
  return (
    (url.hostname === "www.upwork.com" || url.hostname === "upwork.com") &&
    (url.pathname.startsWith("/jobs/") || url.pathname.startsWith("/ab/proposals/job/"))
  )
}

export function parseUpworkJob(document: Document, rawUrl: string): ParseJobResult {
  let url: URL
  try {
    url = new URL(rawUrl)
  } catch {
    return { ok: false, reason: "unsupported" }
  }
  if (!isSupportedUpworkJob(url)) return { ok: false, reason: "unsupported" }

  const structured = structuredJob(document)
  const title =
    stringValue(structured?.title) ??
    firstText(document, ['[data-test="job-title"]', "main h1", "h1"])
  const description =
    stringValue(structured?.description) ??
    firstText(document, [
      '[data-test="description"]',
      '[data-test="Description"]',
      'section[data-test="job-description"]',
    ])

  if (!title || !description) return { ok: false, reason: "incomplete" }

  const structuredSkills = Array.isArray(structured?.skills)
    ? structured.skills.filter((skill): skill is string => typeof skill === "string")
    : typeof structured?.skills === "string"
      ? structured.skills.split(",")
      : []
  const domSkills = [...document.querySelectorAll('[data-test="skill"], [data-test="TokenClamp"]')]
    .map((element) => text(element))
    .filter((skill): skill is string => Boolean(skill))
  const budget = firstText(document, [
    '[data-test="budget"]',
    '[data-test="job-type-label"]',
    '[data-test="budget-and-project-type"]',
  ])

  const pathParts = url.pathname.split("/").filter(Boolean)
  const id = pathParts.at(-1) ?? url.pathname

  return {
    ok: true,
    job: {
      id,
      url: url.toString(),
      title,
      description,
      skills: unique(domSkills.length ? domSkills : structuredSkills),
      ...parseBudget(budget),
      experienceLevel: firstText(document, ['[data-test="experience-level"]']),
      postedAgo: firstText(document, ['[data-test="posted-on"]', '[data-test="posted-date"]']),
      clientRating: parseRating(firstText(document, ['[data-test="client-rating"]'])),
      clientSpend: parseCompactMoney(firstText(document, ['[data-test="client-spend"]'])),
    },
  }
}

export function scrollToApplyAction(document: Document) {
  const explicit = document.querySelector<HTMLElement>(
    '[data-test="apply-button"], [data-test="submit-proposal-button"]',
  )
  const action =
    explicit ??
    [...document.querySelectorAll<HTMLElement>("button, a")].find((element) =>
      /apply now|submit a proposal/i.test(text(element) ?? ""),
    )
  if (!action) return false
  action.scrollIntoView({ behavior: "smooth", block: "center" })
  action.focus({ preventScroll: true })
  return true
}
