import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { goAnalysis } from "@/lib/mock-data"
import { messages } from "@/lib/i18n/messages"
import { FeedbackScreen } from "./feedback-screen"

describe("FeedbackScreen", () => {
  it("saves a corrected score and note", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(
      <FeedbackScreen
        analysis={goAnalysis}
        copy={messages.en}
        onSave={onSave}
        onCancel={() => {}}
      />,
    )

    const score = screen.getByLabelText("Correct score")
    await user.clear(score)
    await user.type(score, "65")
    await user.type(
      screen.getByLabelText("What did we miss?"),
      "Timezone overlap is a blocker",
    )
    await user.click(screen.getByRole("button", { name: "Save feedback" }))

    expect(onSave).toHaveBeenCalledWith({
      correctedScore: 65,
      note: "Timezone overlap is a blocker",
    })
  })

  it("renders Russian labels from the selected locale", () => {
    render(
      <FeedbackScreen
        analysis={goAnalysis}
        copy={messages.ru}
        onSave={() => {}}
        onCancel={() => {}}
      />,
    )

    expect(screen.getByText("Исправить оценку")).toBeVisible()
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeVisible()
  })
})
