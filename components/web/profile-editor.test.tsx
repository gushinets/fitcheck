import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { webMessages } from "@/lib/i18n/web-messages"
import { ProfileEditor } from "./profile-editor"

describe("ProfileEditor", () => {
  it("builds a real profile from empty fields", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<ProfileEditor profile={null} copy={webMessages.en} onSave={onSave} />)

    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled()
    await user.type(screen.getByLabelText("Specialization"), "Backend Developer")
    await user.type(screen.getByLabelText("Skills"), "TypeScript, PostgreSQL")
    await user.clear(screen.getByLabelText("Experience"))
    await user.type(screen.getByLabelText("Experience"), "4")
    await user.clear(screen.getByLabelText("Preferred hourly rate"))
    await user.type(screen.getByLabelText("Preferred hourly rate"), "45")
    await user.selectOptions(screen.getByLabelText("English level"), "Advanced")
    await user.click(screen.getByRole("button", { name: "Save profile" }))

    expect(onSave).toHaveBeenCalledWith({
      specialization: "Backend Developer",
      skills: ["TypeScript", "PostgreSQL"],
      experienceYears: 4,
      preferredRate: 45,
      englishLevel: "Advanced",
    })
  })
})
