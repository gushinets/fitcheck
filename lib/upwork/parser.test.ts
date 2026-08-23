import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it, vi } from "vitest"
import { parseUpworkJob, scrollToApplyAction } from "./parser"

function fixture(name: string) {
  return readFileSync(
    resolve(process.cwd(), `lib/upwork/__fixtures__/${name}.html`),
    "utf8",
  )
}

function load(html: string) {
  document.open()
  document.write(html)
  document.close()
}

describe("parseUpworkJob", () => {
  it("extracts a complete Upwork job", () => {
    load(fixture("complete"))

    expect(
      parseUpworkJob(document, "https://www.upwork.com/jobs/~0123456789"),
    ).toEqual({
      ok: true,
      job: {
        id: "~0123456789",
        url: "https://www.upwork.com/jobs/~0123456789",
        title: "Senior Python Backend Developer",
        description: "Build and maintain a Django API for our growing product.",
        skills: ["Python", "Django", "PostgreSQL"],
        hourlyRateMin: 30,
        hourlyRateMax: 50,
        experienceLevel: "Intermediate",
        postedAgo: "Posted 2 hours ago",
        clientRating: 4.9,
        clientSpend: 25_000,
      },
    })
  })

  it("returns incomplete when description is absent", () => {
    load(fixture("partial"))

    expect(
      parseUpworkJob(document, "https://www.upwork.com/jobs/~0123456789"),
    ).toEqual({ ok: false, reason: "incomplete" })
  })

  it("returns unsupported outside an Upwork job URL", () => {
    load(fixture("complete"))

    expect(parseUpworkJob(document, "https://example.com/job/1")).toEqual({
      ok: false,
      reason: "unsupported",
    })
  })

  it("parses a fixed budget without inventing an hourly rate", () => {
    load(`
      <h1 data-test="job-title">Fixed-price API project</h1>
      <div data-test="description">Deliver a documented API integration.</div>
      <span data-test="budget">$1,200 fixed-price</span>
    `)

    const result = parseUpworkJob(
      document,
      "https://www.upwork.com/jobs/~fixed123",
    )

    expect(result).toMatchObject({
      ok: true,
      job: { fixedBudget: 1200, skills: [] },
    })
    if (result.ok) {
      expect(result.job.hourlyRateMin).toBeUndefined()
    }
  })
})

describe("scrollToApplyAction", () => {
  it("scrolls a detected apply action into view", () => {
    load(fixture("complete"))
    const button = document.querySelector<HTMLElement>("[data-test='apply-button']")!
    button.scrollIntoView = vi.fn()

    expect(scrollToApplyAction(document)).toBe(true)
    expect(button.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "center",
    })
  })
})
