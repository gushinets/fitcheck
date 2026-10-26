// @vitest-environment node

import { describe, expect, it } from "vitest"
import type { AnalysisRequest, SkillLevel } from "@/lib/types"
import { createOpenAITransport } from "./openai"
import { analyzeJob } from "./service"

// Explicit opt-in: this evaluation calls the real provider and consumes API credits.
const enabled = process.env.FITCHECK_RUN_LIVE_EVAL === "1"

describe.skipIf(!enabled)("live skill proficiency scoring", () => {
  it("scores primary and confident n8n above basic and explains the basic-level risk", async () => {
    const apiKey = process.env.OPEN_AI_KEY
    if (!apiKey) throw new Error("OPEN_AI_KEY is required for the live evaluation")
    const transport = createOpenAITransport({ apiKey, model: process.env.OPEN_AI_MODEL })
    const request: AnalysisRequest = {
      profile: {
        specialization: "Automation developer",
        skills: ["Make.com", "n8n"],
        experienceYears: 3, preferredRate: 25,
        workFormats: ["remote"], englishLevel: "Advanced",
      },
      job: {
        id: "proficiency-eval-n8n", title: "Production n8n automation developer",
        description: "Independently design, deploy and maintain complex production n8n workflows with API authentication, webhooks, branching and error recovery. Strong hands-on n8n proficiency is essential; Make.com experience alone is insufficient. Work remotely, communicate in English. Budget is $25 per hour.",
        skills: ["n8n"], hourlyRateMin: 25, hourlyRateMax: 25,
      },
      locale: "en", memory: [],
    }
    const run = (level: SkillLevel) => analyzeJob({
      ...request,
      profile: { ...request.profile, skillLevels: { "make.com": "primary", n8n: level } },
    }, transport)
    const [primary, confident, basic] = await Promise.all([
      run("primary"), run("confident"), run("basic"),
    ])
    expect(primary.score).toBeGreaterThan(basic.score)
    expect(confident.score).toBeGreaterThan(basic.score)
    expect(primary.breakdown.skills).toBeGreaterThan(basic.breakdown.skills)
    expect(confident.breakdown.skills).toBeGreaterThan(basic.breakdown.skills)
    expect(basic.risks.join(" ")).toMatch(/n8n/i)
    expect(basic.risks.join(" ")).toMatch(/basic|limited|beginner/i)
  }, 150_000)
})
