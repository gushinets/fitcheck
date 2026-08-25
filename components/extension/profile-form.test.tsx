import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ProfileForm } from "./profile-form"

describe("ProfileForm", () => {
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
