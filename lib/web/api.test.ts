import { afterEach, describe, expect, it, vi } from "vitest"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import { analyzeVacancy, extractVacancy } from "./api"

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
})
