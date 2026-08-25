import { load, type CheerioAPI } from "cheerio"
import type { PublicPageResponse } from "./network"
import {
  extractedVacancySchema,
  type ExtractedVacancy,
} from "./schema"

type JsonRecord = Record<string, unknown>

function record(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : null
}

function normalizedLines(value: string) {
  const seen = new Set<string>()
  const lines: string[] = []
  for (const rawLine of value.split(/\n+/)) {
    const line = rawLine.replace(/\s+/g, " ").trim()
    if (line && !seen.has(line)) {
      seen.add(line)
      lines.push(line)
    }
  }
  return lines.join("\n")
}

function htmlFragmentText(value: string) {
  const withBreaks = value.replace(
    /<\/(p|div|li|section|article|h[1-6])>/gi,
    "</$1>\n",
  )
  return normalizedLines(load(withBreaks).text())
}

function findJobPosting(value: unknown): JsonRecord | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findJobPosting(item)
      if (found) return found
    }
    return null
  }
  const candidate = record(value)
  if (!candidate) return null
  const type = candidate["@type"]
  if (
    type === "JobPosting" ||
    (Array.isArray(type) && type.includes("JobPosting"))
  ) {
    return candidate
  }
  return findJobPosting(candidate["@graph"])
}

function structuredJob($: CheerioAPI) {
  for (const element of $("script[type='application/ld+json']").toArray()) {
    try {
      const found = findJobPosting(JSON.parse($(element).text()))
      if (found) return found
    } catch {
      continue
    }
  }
  return null
}

function textValue(value: unknown) {
  return typeof value === "string" ? value.trim() : ""
}

function structuredSkills(value: unknown) {
  const values = Array.isArray(value)
    ? value.filter((skill): skill is string => typeof skill === "string")
    : typeof value === "string"
      ? value.split(/[,;|]/)
      : []
  return values.map((skill) => skill.trim()).filter(Boolean)
}

function uniqueSkills(values: string[]) {
  const skills: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    const skill = value.replace(/\s+/g, " ").trim().slice(0, 80)
    const key = skill.toLowerCase()
    if (skill && !seen.has(key)) {
      seen.add(key)
      skills.push(skill)
    }
  }
  return skills.slice(0, 100)
}

function salaryFields(jobPosting: JsonRecord | null) {
  const baseSalary = record(jobPosting?.baseSalary)
  const value = record(baseSalary?.value)
  const unit = textValue(value?.unitText).toUpperCase()
  if (!value) return {}
  const min = Number(value.minValue ?? value.value)
  const max = Number(value.maxValue ?? value.value)
  if (!Number.isFinite(min)) return {}
  if (unit.includes("HOUR")) {
    return {
      hourlyRateMin: min,
      ...(Number.isFinite(max) ? { hourlyRateMax: max } : {}),
    }
  }
  return { fixedBudget: min }
}

function visibleDescription($: CheerioAPI) {
  const selection = $(
    "article, [class*='job-description'], [data-test*='description'], main, body",
  ).first()
  const copy = selection.clone()
  copy.find("h1, h2, h3, nav, header, footer, form").remove()
  copy.find("p, li, div, section").each((_index, element) => {
    $(element).append("\n")
  })
  return normalizedLines(copy.text())
}

function extractHtml(page: PublicPageResponse): ExtractedVacancy {
  const $ = load(page.body)
  const jobPosting = structuredJob($)
  $("script, style, noscript, nav, header, footer, form, [hidden]").remove()

  const title =
    textValue(jobPosting?.title) ||
    $("meta[property='og:title']").attr("content")?.trim() ||
    $("h1").first().text().trim() ||
    $("title").text().trim()
  const structuredDescription = textValue(jobPosting?.description)
  const description = structuredDescription
    ? htmlFragmentText(structuredDescription)
    : visibleDescription($)
  const visibleSkills = $("[class*='skill'] li, [data-test*='skill']")
    .toArray()
    .map((element) => $(element).text())

  return extractedVacancySchema.parse({
    sourceUrl: page.finalUrl,
    title: title.slice(0, 300),
    description: description.slice(0, 20_000),
    skills: uniqueSkills([
      ...structuredSkills(jobPosting?.skills),
      ...visibleSkills,
    ]),
    ...salaryFields(jobPosting),
  })
}

function extractPlainText(page: PublicPageResponse): ExtractedVacancy {
  const lines = normalizedLines(page.body).split("\n")
  return extractedVacancySchema.parse({
    sourceUrl: page.finalUrl,
    title: (lines.shift() ?? "").slice(0, 300),
    description: lines.join("\n").slice(0, 20_000),
    skills: [],
  })
}

export function extractVacancyContent(page: PublicPageResponse) {
  return page.contentType === "text/plain"
    ? extractPlainText(page)
    : extractHtml(page)
}
