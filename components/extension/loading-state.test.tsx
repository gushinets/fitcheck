import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { messages } from "@/lib/i18n/messages"
import { LoadingState } from "./loading-state"

describe("LoadingState", () => {
  it("keeps the Russian task analysis screen fully localized", () => {
    render(<LoadingState copy={messages.ru} />)

    expect(screen.getByText("Сравниваем задачу с вашим профилем.")).toBeVisible()
    expect(screen.queryByText(/comparing this task/i)).not.toBeInTheDocument()
  })
})
