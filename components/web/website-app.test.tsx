import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { WebsiteApi } from "@/lib/web/api"
import { createMemoryWebsiteRepository } from "@/lib/web/memory-repository"
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
