import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
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
  it.each(["en", "ru"] as const)("edits a legacy profile without monthly income (%s)", async (locale) => {
    let saved: FreelancerProfile | undefined
    const legacy = { ...defaultProfile, desiredMonthlyIncome: 250000 }
    render(<ProfileEditor profile={legacy} locale={locale} copy={webMessages[locale]} onSave={(profile) => { saved = profile }} onSuggestSkills={vi.fn()} />)
    expect(screen.queryByLabelText(/Desired monthly income|Желаемый доход в месяц/)).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole("button", { name: webMessages[locale].saveChanges }))
    expect(saved).toMatchObject({ preferredRate: defaultProfile.preferredRate })
    expect(saved).not.toHaveProperty("desiredMonthlyIncome")
  })
  it("restores legacy duplicate skills as a single tag", async () => {
    const onSave = vi.fn()
    render(<ProfileEditor profile={{ ...defaultProfile, skills: ["Python", "python"], skillLevels: { python: "primary" } }} locale="en" copy={webMessages.en} onSave={onSave} onSuggestSkills={vi.fn()} />)
    expect(screen.getAllByRole("combobox", { name: /^Proficiency:/ })).toHaveLength(1)
    await userEvent.setup().click(screen.getByRole("button", { name: "Save changes" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: ["Python"], skillLevels: { python: "primary" } }))
  })
  it.each(["en", "ru"] as const)("adds separate trimmed tags on Enter without submitting (%s)", async (locale) => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    render(<ProfileEditor profile={{ ...defaultProfile, skills: ["Python"] }} locale={locale} copy={webMessages[locale]} onSave={onSave} onSuggestSkills={vi.fn()} />)
    const input = screen.getByLabelText(webMessages[locale].skills)
    await user.type(input, "  n8n  {Enter}")
    expect(input).toHaveValue("")
    expect(screen.getByRole("combobox", { name: `${webMessages[locale].skillLevel}: n8n` })).toBeVisible()
    await user.type(input, " Make.com{Enter}  N8N {Enter}   {Enter}")
    expect(screen.getAllByRole("combobox", { name: new RegExp(`^${webMessages[locale].skillLevel}:`) })).toHaveLength(3)
    expect(onSave).not.toHaveBeenCalled()
    await user.selectOptions(screen.getByRole("combobox", { name: `${webMessages[locale].skillLevel}: n8n` }), "basic")
    await user.click(screen.getByRole("button", { name: webMessages[locale].saveChanges }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: ["Python", "n8n", "Make.com"], skillLevels: { n8n: "basic" } }))
  })

  it("does not commit a skill while an IME composition is active", async () => {
    renderEditor()
    const input = screen.getByLabelText("Skills")
    fireEvent.change(input, { target: { value: "日本語" } })
    fireEvent.keyDown(input, { key: "Enter", isComposing: true })
    expect(input).toHaveValue("日本語")
    expect(screen.queryByRole("combobox", { name: "Proficiency: 日本語" })).not.toBeInTheDocument()
    await userEvent.setup().type(input, "{Enter}")
    expect(input).toHaveValue("")
    expect(screen.getByRole("combobox", { name: "Proficiency: 日本語" })).toBeVisible()
  })
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
    await user.click(screen.getByRole("button", { name: "Remove skill: n8n" }))
    expect(screen.queryByRole("combobox", { name: "Proficiency: n8n" })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText("Skills"), "n8n{Enter}")
    expect(screen.getByRole("combobox", { name: "Proficiency: n8n" })).toHaveValue("")
    await user.click(screen.getByRole("button", { name: "Remove skill: n8n" }))
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: ["Make.com"], skillLevels: { "make.com": "primary" } }))
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
    expect(screen.getByLabelText("Skills")).toHaveValue("")
    expect(screen.getByRole("combobox", { name: "Proficiency: Python" })).toBeVisible()
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

  it("saves large rates and selected work formats", async () => {
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
      workFormats: ["remote", "hybrid"],
      englishLevel: "Advanced",
    })
  })

  it("saves fractional hourly rates", async () => {
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
    await user.click(screen.getByRole("checkbox", { name: "Remote" }))

    expect(screen.getByRole("button", { name: "Save profile" })).toBeEnabled()
    await user.click(screen.getByRole("button", { name: "Save profile" }))

    expect(onSave).toHaveBeenCalledWith({
      specialization: "Backend Developer",
      skills: ["TypeScript"],
      experienceYears: 0,
      preferredRate: 45.5,
      workFormats: ["remote"],
      englishLevel: "Intermediate",
    })
  })

  it.each([
    ["en" as const, "/hour", "Work formats", "Office"],
    ["ru" as const, "/час", "Формат работы", "Офис"],
  ])(
    "renders locale-specific currency and work-format labels for %s",
    (locale, hourlyCurrency, workFormats, office) => {
      renderEditor({ locale })

      expect(screen.getByText(hourlyCurrency)).toBeVisible()
      expect(screen.getByText(workFormats)).toBeVisible()
      expect(screen.getByRole("checkbox", { name: office })).toBeVisible()
    },
  )
})

it("observes accepted suggestion after adding it and isolates throwing telemetry", async () => {
  const onSkillsAccepted = vi.fn(() => { throw Error("collector") })
  render(<ProfileEditor profile={null} locale="en" copy={webMessages.en} onSave={vi.fn()} onSuggestSkills={async () => ["Python"]} onSkillsAccepted={onSkillsAccepted} />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText("Specialization"), "Backend")
  await user.click(screen.getByRole("button", { name: "Suggest skills" }))
  await user.click(await screen.findByRole("button", { name: "Python" }))
  expect(onSkillsAccepted.mock.calls).toEqual([[1]])
  expect(screen.getByRole("combobox", { name: "Proficiency: Python" })).toBeVisible()
})
