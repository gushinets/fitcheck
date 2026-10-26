import { afterEach, describe, expect, it, vi } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { analyzeVacancy, analyzeVacancyWithContext, extractVacancy, suggestSkills } from "./api"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("website API client", () => {
  it("turns extracted page data into an editable URL draft", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          sourceUrl: "https://jobs.example/role",
          title: "Backend Engineer",
          description: "Build reliable APIs for a production SaaS platform.",
          skills: ["TypeScript"],
        }),
      ),
    )

    await expect(extractVacancy("https://jobs.example/role")).resolves.toMatchObject({
      sourceMode: "url",
      sourceUrl: "https://jobs.example/role",
      title: "Backend Engineer",
      skills: ["TypeScript"],
    })
  })

  it("maps stable server errors and malformed success responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ error: "blocked_address" }, { status: 403 }),
      ),
    )
    await expect(
      extractVacancy("http://127.0.0.1/role"),
    ).rejects.toMatchObject({ code: "blocked_address" })

    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ score: 82 })))
    await expect(
      analyzeVacancy({
        profile: defaultProfile,
        job: detectedJob,
        locale: "en",
        memory: [],
      }),
    ).rejects.toMatchObject({ code: "invalid_response" })
  })

  it("returns a validated real-analysis response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(goAnalysis)))

    await expect(
      analyzeVacancy({
        profile: defaultProfile,
        job: detectedJob,
        locale: "en",
        memory: [],
      }),
    ).resolves.toEqual(goAnalysis)
  })

  it("posts specialization and locale then returns validated skill suggestions", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ skills: ["TypeScript", "PostgreSQL"] }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await expect(
      suggestSkills({ specialization: "Backend engineering", locale: "en" }),
    ).resolves.toEqual(["TypeScript", "PostgreSQL"])

    expect(fetchMock).toHaveBeenCalledWith("/api/skill-suggestions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ specialization: "Backend engineering", locale: "en" }),
    })
  })

  it("maps skill suggestion timeout errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ error: "suggestions_timeout" }, { status: 504 }),
      ),
    )

    await expect(
      suggestSkills({ specialization: "Backend engineering", locale: "en" }),
    ).rejects.toMatchObject({ code: "suggestions_timeout" })
  })

  it.each([
    [{ skills: Array.from({ length: 11 }, () => "TypeScript") }],
    [{ skills: ["TypeScript", ""] }],
  ])("rejects malformed skill suggestion success data: %o", async (payload) => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(payload)))

    await expect(
      suggestSkills({ specialization: "Backend engineering", locale: "en" }),
    ).rejects.toMatchObject({ code: "invalid_response" })
  })
})

const operationId = "11111111-1111-4111-8111-111111111111"
it.each([operationId, "invalid-private-value", null])("keeps validated operation header separate from public analysis JSON: %s", async (header) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(goAnalysis, { headers: header ? { "X-FitCheck-Operation-Id": header } : {} })))
  const request = {profile: defaultProfile, job: detectedJob, locale: "en" as const, memory: []}
  await expect(analyzeVacancyWithContext(request)).resolves.toEqual({analysis: goAnalysis, ...(header === operationId ? {operationId} : {})})
  await expect(analyzeVacancy(request)).resolves.toEqual(goAnalysis)
})
