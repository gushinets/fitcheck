import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { webMessages } from "@/lib/i18n/web-messages"
import type { SkillSuggestionRequest } from "@/lib/skill-suggestions/schema"
import type { FreelancerProfile, Locale } from "@/lib/types"
import { ProfileEditor } from "./profile-editor"
import { defaultProfile } from "@/lib/mock-data"

function renderEditor({
  locale = "en",
  onSave = vi.fn(),
  onSuggestSkills = vi.fn(async () => []),
}: {
  locale?: Locale
  onSave?: (profile: FreelancerProfile) => void
  onSuggestSkills?: (input: SkillSuggestionRequest) => Promise<string[]>
} = {}) {
  render(
    <ProfileEditor
      profile={null}
      locale={locale}
      copy={webMessages[locale]}
      onSave={onSave}
      onSuggestSkills={onSuggestSkills}
    />,
  )
}

describe("ProfileEditor", () => {
  it.each(["USD", "EUR", "RUB"] as const)("saves %s without converting the rate", async (currency) => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<ProfileEditor profile={{ ...defaultProfile, preferredRate: 25, rateCurrency: "USD" }} locale="ru" copy={webMessages.ru} onSave={onSave} onSuggestSkills={vi.fn()} />)
    await user.selectOptions(screen.getByRole("combobox", { name: "Валюта ставки" }), currency)
    await user.click(screen.getByRole("button", { name: "Сохранить изменения" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ preferredRate: 25, rateCurrency: currency }))
  })
  it("changes and saves a level for each skill", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<ProfileEditor profile={{ ...defaultProfile, skills: ["Make.com", "n8n"], skillLevels: { "make.com": "primary", n8n: "confident" } }} locale="ru" copy={webMessages.ru} onSave={onSave} onSuggestSkills={vi.fn()} />)
    expect(screen.getByRole("combobox", { name: "Уровень: Make.com" })).toHaveValue("primary")
    await user.selectOptions(screen.getByRole("combobox", { name: "Уровень: n8n" }), "basic")
    await user.click(screen.getByRole("button", { name: "Сохранить изменения" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skillLevels: { "make.com": "primary", n8n: "basic" } }))
  })

  it("removes orphaned levels when a skill is deleted", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<ProfileEditor profile={{ ...defaultProfile, skills: ["Make.com", "n8n"], skillLevels: { "make.com": "primary", n8n: "basic" } }} locale="en" copy={webMessages.en} onSave={onSave} onSuggestSkills={vi.fn()} />)
    await user.clear(screen.getByLabelText("Skills"))
    await user.type(screen.getByLabelText("Skills"), "MAKE.COM")
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: ["MAKE.COM"], skillLevels: { "make.com": "primary" } }))
  })

  it("suggests skills on demand, excludes duplicates, and appends a selected chip", async () => {
    const user = userEvent.setup()
    const onSuggestSkills = vi.fn(async () => [
      "typescript",
      "Python",
      "PostgreSQL",
    ])
    renderEditor({
      onSuggestSkills,
    })

    expect(
      screen.getByRole("button", { name: "Suggest skills" }),
    ).toBeDisabled()
    await user.type(
      screen.getByLabelText("Specialization"),
      "Backend Developer",
    )
    await user.type(screen.getByLabelText("Skills"), "TypeScript")
    await user.click(screen.getByRole("button", { name: "Suggest skills" }))

    expect(onSuggestSkills).toHaveBeenCalledWith({
      specialization: "Backend Developer",
      locale: "en",
    })
    expect(
      screen.queryByRole("button", { name: "typescript" }),
    ).not.toBeInTheDocument()
    expect(await screen.findByRole("button", { name: "Python" })).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Python" }))
    expect(screen.getByLabelText("Skills")).toHaveValue("TypeScript, Python")
    expect(
      screen.queryByRole("button", { name: "Python" }),
    ).not.toBeInTheDocument()
  })

  it("filters existing skills before limiting suggestions to 10 chips", async () => {
    const user = userEvent.setup()
    renderEditor({
      onSuggestSkills: vi.fn(async () => [
        "typescript",
        "Skill 1",
        "Skill 2",
        "Skill 3",
        "Skill 4",
        "Skill 5",
        "Skill 6",
        "Skill 7",
        "Skill 8",
        "Skill 9",
        "Skill 10",
        "Skill 11",
      ]),
    })

    await user.type(
      screen.getByLabelText("Specialization"),
      "Backend Developer",
    )
    await user.type(screen.getByLabelText("Skills"), "TypeScript")
    await user.click(screen.getByRole("button", { name: "Suggest skills" }))

    expect(await screen.findAllByRole("button", { name: /^Skill \d+$/ })).toHaveLength(10)
    expect(
      screen.queryByRole("button", { name: "typescript" }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Skill 10" })).toBeVisible()
    expect(
      screen.queryByRole("button", { name: "Skill 11" }),
    ).not.toBeInTheDocument()
  })

  it("clears stale suggestions when the specialization changes", async () => {
    const user = userEvent.setup()
    renderEditor({
      onSuggestSkills: vi.fn(async () => ["Python"]),
    })

    const specialization = screen.getByLabelText("Specialization")
    await user.type(specialization, "Backend Developer")
    await user.click(screen.getByRole("button", { name: "Suggest skills" }))
    expect(await screen.findByRole("button", { name: "Python" })).toBeVisible()

    await user.type(specialization, " II")

    expect(
      screen.queryByRole("button", { name: "Python" }),
    ).not.toBeInTheDocument()
  })

  it("renders a suggestion failure inline and allows another attempt", async () => {
    const user = userEvent.setup()
    renderEditor({
      onSuggestSkills: vi.fn(async () => {
        throw new Error("Skill suggestions took too long. Try again.")
      }),
    })

    await user.type(
      screen.getByLabelText("Specialization"),
      "Backend Developer",
    )
    await user.click(screen.getByRole("button", { name: "Suggest skills" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Skill suggestions took too long. Try again.",
    )
    expect(
      screen.getByRole("button", { name: "Suggest skills" }),
    ).toBeEnabled()
  })

  it("saves large rates, monthly income, and selected work formats", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    renderEditor({ onSave })

    await user.type(
      screen.getByLabelText("Specialization"),
      "Backend Developer",
    )
    await user.type(screen.getByLabelText("Skills"), "TypeScript, PostgreSQL")
    await user.clear(screen.getByLabelText("Experience"))
    await user.type(screen.getByLabelText("Experience"), "4")
    await user.clear(screen.getByLabelText("Preferred hourly rate"))
    await user.type(screen.getByLabelText("Preferred hourly rate"), "2500")
    await user.clear(screen.getByLabelText("Desired monthly income"))
    await user.type(screen.getByLabelText("Desired monthly income"), "7500")
    await user.selectOptions(screen.getByLabelText("English level"), "Advanced")

    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled()
    await user.click(screen.getByRole("checkbox", { name: "Remote" }))
    await user.click(screen.getByRole("checkbox", { name: "Hybrid" }))
    await user.click(screen.getByRole("button", { name: "Save profile" }))

    expect(onSave).toHaveBeenCalledWith({
      specialization: "Backend Developer",
      skills: ["TypeScript", "PostgreSQL"],
      experienceYears: 4,
      preferredRate: 2500,
      desiredMonthlyIncome: 7500,
      workFormats: ["remote", "hybrid"],
      englishLevel: "Advanced",
    })
  })

  it("saves fractional hourly rate and monthly income values", async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    renderEditor({ onSave })

    await user.type(
      screen.getByLabelText("Specialization"),
      "Backend Developer",
    )
    await user.type(screen.getByLabelText("Skills"), "TypeScript")
    await user.clear(screen.getByLabelText("Preferred hourly rate"))
    await user.type(screen.getByLabelText("Preferred hourly rate"), "45.5")
    await user.clear(screen.getByLabelText("Desired monthly income"))
    await user.type(screen.getByLabelText("Desired monthly income"), "7500.25")
    await user.click(screen.getByRole("checkbox", { name: "Remote" }))

    expect(screen.getByRole("button", { name: "Save profile" })).toBeEnabled()
    await user.click(screen.getByRole("button", { name: "Save profile" }))

    expect(onSave).toHaveBeenCalledWith({
      specialization: "Backend Developer",
      skills: ["TypeScript"],
      experienceYears: 0,
      preferredRate: 45.5,
      desiredMonthlyIncome: 7500.25,
      workFormats: ["remote"],
      englishLevel: "Intermediate",
    })
  })

  it("keeps save disabled when monthly income is blank", async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.type(
      screen.getByLabelText("Specialization"),
      "Backend Developer",
    )
    await user.type(screen.getByLabelText("Skills"), "TypeScript")
    await user.click(screen.getByRole("checkbox", { name: "Remote" }))

    const monthlyIncome = screen.getByLabelText("Desired monthly income")
    expect(screen.getByRole("button", { name: "Save profile" })).toBeEnabled()

    await user.clear(monthlyIncome)

    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled()
    expect(monthlyIncome).toBeRequired()
  })

  it.each([
    ["en" as const, "/hour", "$/month", "Work formats", "Office"],
    ["ru" as const, "/час", "₽/месяц", "Формат работы", "Офис"],
  ])(
    "renders locale-specific currency and work-format labels for %s",
    (locale, hourlyCurrency, monthlyCurrency, workFormats, office) => {
      renderEditor({ locale })

      expect(screen.getByText(hourlyCurrency)).toBeVisible()
      expect(screen.getByText(monthlyCurrency)).toBeVisible()
      expect(screen.getByText(workFormats)).toBeVisible()
      expect(screen.getByRole("checkbox", { name: office })).toBeVisible()
    },
  )
})
