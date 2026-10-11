// @vitest-environment node

import { readFileSync } from "node:fs"
import { afterEach, describe, expect, it, vi } from "vitest"
import { extractVacancyContent } from "@/lib/extraction/content"
import { createDeepSeekTransport } from "./deepseek"
import { analyzeJob } from "./service"

const enabled = process.env.FITCHECK_RUN_LIVE_EVAL === "1"

describe.skipIf(!enabled)("ANY-531 live report grounding", () => {
  afterEach(() => vi.unstubAllGlobals())
  it.each(["lead-generation", "shopify"])("does not invent profile facts for %s", async (name) => {
    if (!process.env.DEEPSEEK_API_KEY) throw new Error("DEEPSEEK_API_KEY is required")
    if (process.env.FITCHECK_LIVE_DEBUG === "1") {
      const fetch = globalThis.fetch
      vi.stubGlobal("fetch", async (...args: Parameters<typeof fetch>) => {
        const response = await fetch(...args)
        const body = await response.clone().json()
        process.stderr.write(JSON.stringify({ example: name, output: body.choices?.[0]?.message?.content }) + "\n")
        return response
      })
    }
    const extracted = extractVacancyContent({ finalUrl: "https://www.freelancer.com/projects/test/" + name, contentType: "text/html", body: readFileSync(new URL(`../extraction/__fixtures__/freelancer-${name}.html`, import.meta.url), "utf8") })
    const result = await analyzeJob({
      profile: { specialization: "Make.com automation specialist", skills: ["Make.com", "n8n"], skillLevels: { "make.com": "primary", n8n: "basic" }, experienceYears: 3, preferredRate: 25, rateCurrency: "USD", englishLevel: "Advanced", workFormats: ["remote"] },
      job: { id: name, ...extracted }, locale: "en", memory: [],
    }, createDeepSeekTransport({ apiKey: process.env.DEEPSEEK_API_KEY, model: process.env.DEEPSEEK_MODEL }))
    expect(result.strengths.join(" ")).not.toMatch(/ESP32|LoRa|Rhino|Shopify|Czech/)
    expect(result.strengthEvidence).toHaveLength(result.strengths.length)
    expect(result.strengths.length).toBeLessThanOrEqual(3)
    const report = [result.label, result.summary, ...result.risks].join(" ")
    expect(report).not.toMatch(/(?:speak|fluent\s+in|proficient\s+in)\s+Czech|Czech\s+(?:fluency|proficiency)/i)
    console.info(JSON.stringify({ example: name, score: result.score, strengths: result.strengths, summary: result.summary, risks: result.risks }))
  }, 180_000)
})
