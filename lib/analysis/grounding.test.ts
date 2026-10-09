// @vitest-environment node

import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { defaultProfile, detectedJob } from "@/lib/mock-data"
import { buildStrengthEvidence } from "./grounding"
import { extractVacancyContent } from "@/lib/extraction/content"

describe("profile-grounded strengths", () => {
  it.each(["Удалённая работа", "Удаленный формат"])("recognizes explicit Russian remote work: %s", (description) => {
    const evidence = buildStrengthEvidence({ profile: defaultProfile, job: { ...detectedJob, description }, locale: "ru", memory: [] })
    expect(evidence.find((fact) => fact.id === "workFormat:remote")?.taskFields).toEqual(["description"])
  })
  it("cites only the task field that contains experience evidence", () => {
    const evidence = buildStrengthEvidence({ profile: defaultProfile, job: { ...detectedJob, title: "Experienced Python engineer", description: "Build an API", experienceLevel: undefined }, locale: "en", memory: [] })
    expect(evidence.find((fact) => fact.id === "experience")?.taskFields).toEqual(["title"])
  })

  it.each(["Remote sensing data analysis", "Configure remote desktop", "Connect a remote API"])("does not invent remote work from %s", (description) => {
    const evidence = buildStrengthEvidence({ profile: defaultProfile, job: { ...detectedJob, description }, locale: "en", memory: [] })
    expect(evidence.some((fact) => fact.id === "workFormat:remote")).toBe(false)
  })
  it("renders matching skill facts from the profile without invented proficiency", () => {
    const evidence = buildStrengthEvidence({ profile: defaultProfile, job: detectedJob, locale: "en", memory: [] })
    expect(evidence.find((fact) => fact.id === "skill:0")).toMatchObject({
      text: "Your profile lists Python; this skill appears in the task. Proficiency is not specified.",
      profileFields: ["skills.0"], taskFields: ["skills", "title"],
    })
  })

  it.each(["primary", "confident"] as const)("retains %s proficiency as cited profile evidence", (level) => {
    const evidence = buildStrengthEvidence({ profile: { ...defaultProfile, skillLevels: { python: level } }, job: detectedJob, locale: "en", memory: [] })
    expect(evidence.find((fact) => fact.id === "skill:0")?.profileFields).toEqual(["skills.0", "skillLevels.python"])
  })

  it("does not claim a rate match across currencies", () => {
    const evidence = buildStrengthEvidence({ profile: { ...defaultProfile, rateCurrency: "USD" }, job: { ...detectedJob, budgetCurrency: "EUR" }, locale: "en", memory: [] })
    expect(evidence.some((fact) => fact.id === "rate")).toBe(false)
  })

  it("provides traceable experience, English, remote work and same-currency rate facts", () => {
    const evidence = buildStrengthEvidence({ profile: { ...defaultProfile, rateCurrency: "USD" }, job: { ...detectedJob, budgetCurrency: "USD", description: "Five years of experience. Communicate in English and work remotely." }, locale: "en", memory: [] })
    expect(evidence.map((fact) => fact.id)).toEqual(expect.arrayContaining(["experience", "english", "workFormat:remote", "rate"]))
  })

  it("does not turn the lead-generation task's hardware tools into freelancer strengths", () => {
    const extracted = extractVacancyContent({ finalUrl: "https://www.freelancer.com/projects/b2b-marketing/test", contentType: "text/html", body: readFileSync(new URL("../extraction/__fixtures__/freelancer-lead-generation.html", import.meta.url), "utf8") })
    const evidence = buildStrengthEvidence({
      profile: { ...defaultProfile, skills: ["Make.com", "n8n"], skillLevels: { "make.com": "primary", n8n: "basic" } },
      job: { id: "lead-generation", ...extracted }, locale: "ru", memory: [],
    })
    expect(evidence.filter((fact) => fact.id.startsWith("skill:"))).toEqual([])
    expect(evidence.map((fact) => fact.text).join(" ")).not.toMatch(/ESP32|LoRa|Rhino/)
  })

  it("does not present basic familiarity as a professional strength", () => {
    const evidence = buildStrengthEvidence({ profile: { ...defaultProfile, skills: ["n8n"], skillLevels: { n8n: "basic" } }, job: { ...detectedJob, skills: ["n8n"] }, locale: "en", memory: [] })
    expect(evidence.some((fact) => fact.id === "skill:0")).toBe(false)
  })

  it("does not create Czech proficiency from EN/CZ content-generation requirements", () => {
    const extracted = extractVacancyContent({ finalUrl: "https://www.freelancer.com/projects/shopify-site/test", contentType: "text/html", body: readFileSync(new URL("../extraction/__fixtures__/freelancer-shopify.html", import.meta.url), "utf8") })
    const evidence = buildStrengthEvidence({ profile: defaultProfile, job: { id: "shopify", ...extracted }, locale: "ru", memory: [] })
    expect(evidence.map((fact) => fact.text).join(" ")).not.toMatch(/чеш|Czech|CZ/i)
  })
})
