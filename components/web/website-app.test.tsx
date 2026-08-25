import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { WebsiteApi } from "@/lib/web/api"
import { createMemoryWebsiteRepository } from "@/lib/web/memory-repository"
import { defaultProfile, goAnalysis } from "@/lib/mock-data"
import { WebApiError } from "@/lib/web/api"
import { WebsiteApp } from "./website-app"

const api: WebsiteApi = {
  extractVacancy: vi.fn(),
  analyzeVacancy: vi.fn(),
}

beforeEach(() => {
  window.localStorage.clear()
})

describe("FitCheck website authentication", () => {
  it("creates a remembered local account and switches language", async () => {
    const user = userEvent.setup()
    const repository = createMemoryWebsiteRepository()
    render(<WebsiteApp repository={repository} api={api} />)

    expect(
      await screen.findByText(/account stays in this browser/i),
    ).toBeVisible()
    await user.type(screen.getByLabelText("Name"), "Nikita")
    await user.type(screen.getByLabelText("Email"), "me@example.com")
    await user.type(screen.getByLabelText("Password"), "password-123")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(
      await screen.findByRole("heading", {
        name: "Complete your freelancer profile",
      }),
    ).toBeVisible()
    await user.click(screen.getByRole("button", { name: "RU" }))
    expect(
      await screen.findByRole("heading", {
        name: "Заполните профиль фрилансера",
      }),
    ).toBeVisible()
    expect(screen.getAllByText("Новый анализ")).toHaveLength(2)
  })

  it("restores an existing local session", async () => {
    const repository = createMemoryWebsiteRepository()
    await repository.createUser({
      name: "Nikita",
      email: "me@example.com",
      password: "password-123",
    })

    render(<WebsiteApp repository={repository} api={api} />)

    expect(await screen.findByText("Nikita")).toBeVisible()
    expect(
      screen.getByRole("heading", { name: "Complete your freelancer profile" }),
    ).toBeVisible()
  })

  it("signs out and reports an incorrect local password", async () => {
    const user = userEvent.setup()
    const repository = createMemoryWebsiteRepository()
    await repository.createUser({
      name: "Nikita",
      email: "me@example.com",
      password: "password-123",
    })
    render(<WebsiteApp repository={repository} api={api} />)

    await user.click(await screen.findByRole("button", { name: "Sign out" }))
    await user.click(
      screen.getByRole("button", { name: "Switch to sign in" }),
    )
    await user.type(screen.getByLabelText("Email"), "me@example.com")
    await user.type(screen.getByLabelText("Password"), "wrong-password")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    expect(await screen.findByText("Incorrect password")).toBeVisible()
  })
})

describe("FitCheck vacancy workflow", () => {
  it("returns to source selection with the draft intact and sends a real analysis request", async () => {
    const user = userEvent.setup()
    const repository = createMemoryWebsiteRepository()
    const localUser = await repository.createUser({
      name: "Nikita",
      email: "me@example.com",
      password: "password-123",
    })
    await repository.saveProfile(localUser.id, defaultProfile)
    const analyzeVacancy = vi.fn(async () => goAnalysis)
    render(
      <WebsiteApp
        repository={repository}
        api={{ extractVacancy: vi.fn(), analyzeVacancy }}
      />,
    )

    expect(
      await screen.findByRole("heading", {
        name: "Choose how to add a vacancy",
      }),
    ).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Paste text" }))
    await user.type(screen.getByLabelText("Vacancy title"), "Backend role")
    await user.type(
      screen.getByLabelText("Vacancy description"),
      "Build production APIs for a fast-growing SaaS platform.",
    )
    await user.click(screen.getByRole("button", { name: "Review vacancy" }))
    await user.click(
      screen.getByRole("button", { name: "Back to vacancy selection" }),
    )
    expect(screen.getByLabelText("Vacancy title")).toHaveValue("Backend role")
    await user.click(screen.getByRole("button", { name: "Review vacancy" }))
    await user.click(screen.getByRole("button", { name: "Analyze vacancy" }))

    expect(await screen.findByLabelText("Fit score 82 out of 100")).toBeVisible()
    expect(analyzeVacancy).toHaveBeenCalledWith(
      expect.objectContaining({
        profile: defaultProfile,
        job: expect.objectContaining({ title: "Backend role" }),
        locale: "en",
      }),
    )
    expect((await repository.loadSnapshot()).history).toHaveLength(1)
  })

  it("keeps the reviewed vacancy and skips history when analysis fails", async () => {
    const user = userEvent.setup()
    const repository = createMemoryWebsiteRepository()
    const localUser = await repository.createUser({
      name: "Nikita",
      email: "me@example.com",
      password: "password-123",
    })
    await repository.saveProfile(localUser.id, defaultProfile)
    await repository.saveDraft(localUser.id, {
      id: "draft-1",
      sourceMode: "text",
      title: "Backend role",
      description: "Build production APIs for a fast-growing SaaS platform.",
      skills: ["Python"],
      updatedAt: "2026-08-25T12:00:00.000Z",
    })
    render(
      <WebsiteApp
        repository={repository}
        api={{
          extractVacancy: vi.fn(),
          analyzeVacancy: async () => {
            throw new WebApiError("analysis_upstream")
          },
        }}
      />,
    )

    await user.click(await screen.findByRole("button", { name: "Review vacancy" }))
    await user.click(screen.getByRole("button", { name: "Analyze vacancy" }))

    expect(
      await screen.findByText("The analysis service is temporarily unavailable"),
    ).toBeVisible()
    expect(screen.getByRole("heading", { name: "Review the vacancy" })).toBeVisible()
    expect((await repository.loadSnapshot()).history).toHaveLength(0)
  })
})
