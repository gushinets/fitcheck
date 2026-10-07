import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ProfileForm } from "./profile-form"
import userEvent from "@testing-library/user-event"
import { vi } from "vitest"
import { defaultProfile } from "@/lib/mock-data"

describe("ProfileForm", () => {
  it("preserves proficiency when editing a legacy extension profile", async () => {
    const onSubmit = vi.fn()
    render(<ProfileForm initial={{ ...defaultProfile, skills: ["n8n"], skillLevels: { n8n: "basic" } }} submitLabel="Save profile" onSubmit={onSubmit} />)
    await userEvent.setup().click(screen.getByRole("button", { name: "Save profile" }))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ skillLevels: { n8n: "basic" } }))
  })

  it("does not allow saving a profile without a specialization and skill", () => {
    render(
      <ProfileForm
        initial={{
          specialization: "",
          skills: [],
          experienceYears: 0,
          preferredRate: 0,
          desiredMonthlyIncome: 0,
          workFormats: ["remote"],
          englishLevel: "Intermediate",
        }}
        submitLabel="Save profile"
        onSubmit={() => {}}
      />,
    )

    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled()
  })
})
