import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { webMessages } from "@/lib/i18n/web-messages"
import { WebApiError } from "@/lib/web/api"
import { VacancySource } from "./vacancy-source"

describe("VacancySource", () => {
  it("preserves URL and text buffers while switching input modes", async () => {
    const user = userEvent.setup()
    const onReview = vi.fn()
    render(<VacancySource copy={webMessages.en} onLoadUrl={vi.fn()} onReview={onReview} />)

    await user.click(screen.getByRole("button", { name: "Paste text" }))
    await user.type(screen.getByLabelText("Task title"), "Backend role")
    await user.type(
      screen.getByLabelText("Task description"),
      "Build production APIs for a fast-growing SaaS platform.",
    )
    await user.click(screen.getByRole("button", { name: "From URL" }))
    await user.type(
      screen.getByLabelText("Task URL"),
      "https://jobs.example/backend",
    )
    await user.click(screen.getByRole("button", { name: "Paste text" }))

    expect(screen.getByLabelText("Task title")).toHaveValue("Backend role")
    await user.click(screen.getByRole("button", { name: "Review task" }))
    expect(onReview).toHaveBeenCalledWith(
      expect.objectContaining({ sourceMode: "text", title: "Backend role" }),
    )
  })

  it.each(["extraction_insufficient", "fetch_failed"] as const)("offers manual paste after %s", async (code) => {
    const user = userEvent.setup()
    render(
      <VacancySource
        copy={webMessages.en}
        onLoadUrl={async () => {
          throw new WebApiError(code)
        }}
        onReview={vi.fn()}
      />,
    )

    await user.type(
      screen.getByLabelText("Task URL"),
      "https://www.freelancer.com/projects/n8n/deleted",
    )
    await user.click(screen.getByRole("button", { name: "Load task" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      code === "extraction_insufficient" ? /could not find enough task text/i : /could not be loaded/i,
    )
    await user.click(screen.getByRole("button", { name: "Paste text instead" }))
    expect(screen.getByLabelText("Task description")).toBeVisible()
  })
})
