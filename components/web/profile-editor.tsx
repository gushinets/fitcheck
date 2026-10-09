"use client"

import { useRef, useState } from "react"
import { X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { currencies } from "@/lib/currency"
import { freelancerProfileSchema } from "@/lib/analysis/schema"
import type { WebMessages } from "@/lib/i18n/web-messages"
import type { SkillSuggestionRequest } from "@/lib/skill-suggestions/schema"
import type {
  EnglishLevel,
  Currency,
  FreelancerProfile,
  Locale,
  SkillLevel,
  WorkFormat,
} from "@/lib/types"

const englishLevels: { value: EnglishLevel; label: keyof WebMessages }[] = [
  { value: "Basic", label: "englishBasic" },
  { value: "Intermediate", label: "englishIntermediate" },
  { value: "Upper Intermediate", label: "englishUpperIntermediate" },
  { value: "Advanced", label: "englishAdvanced" },
  { value: "Fluent", label: "englishFluent" },
]

const workFormatOptions: {
  value: WorkFormat
  label: "workRemote" | "workOffice" | "workHybrid"
}[] = [
  { value: "remote", label: "workRemote" },
  { value: "office", label: "workOffice" },
  { value: "hybrid", label: "workHybrid" },
]

function mergeSkills(current: string[], additions: string[]) {
  const next = [...current]
  for (const entry of additions) {
    const skill = entry.trim()
    if (skill && !next.some((existing) => existing.toLowerCase() === skill.toLowerCase())) next.push(skill)
  }
  return next
}

export function ProfileEditor({
  profile,
  locale,
  copy,
  onSave,
  onSuggestSkills,
}: {
  profile: FreelancerProfile | null
  locale: Locale
  copy: WebMessages
  onSave: (profile: FreelancerProfile) => void
  onSuggestSkills: (input: SkillSuggestionRequest) => Promise<string[]>
}) {
  const [specialization, setSpecialization] = useState(profile?.specialization ?? "")
  const [skills, setSkills] = useState<string[]>(() => mergeSkills([], profile?.skills ?? []))
  const [skillInput, setSkillInput] = useState("")
  const [skillLevels, setSkillLevels] = useState<Record<string, SkillLevel>>(profile?.skillLevels ?? {})
  const [experience, setExperience] = useState(String(profile?.experienceYears ?? 0))
  const [rate, setRate] = useState(String(profile?.preferredRate ?? 0))
  const [rateCurrency, setRateCurrency] = useState<Currency | "">(profile?.rateCurrency ?? "")
  const [monthlyIncome, setMonthlyIncome] = useState(
    String(profile?.desiredMonthlyIncome ?? 0),
  )
  const [workFormats, setWorkFormats] = useState<WorkFormat[]>(
    profile?.workFormats ?? [],
  )
  const [englishLevel, setEnglishLevel] = useState<EnglishLevel>(profile?.englishLevel ?? "Intermediate")
  const [suggestions, setSuggestions] = useState<string[] | null>(null)
  const [suggestionError, setSuggestionError] = useState<string | null>(null)
  const [suggesting, setSuggesting] = useState(false)
  const suggestionRequestId = useRef(0)
  const skillsToSave = mergeSkills(skills, skillInput.split(","))
  const normalizedSkills = new Set(
    skillsToSave.map((skill) => skill.toLowerCase()),
  )
  const visibleSuggestions = suggestions?.filter(
    (skill) => !normalizedSkills.has(skill.toLowerCase()),
  )
  const profileCandidate = {
    specialization,
    skills: skillsToSave,
    ...(Object.keys(skillLevels).length ? {
      skillLevels: Object.fromEntries(Object.entries(skillLevels).filter(([key]) => normalizedSkills.has(key))),
    } : {}),
    experienceYears: Number(experience),
    preferredRate: Number(rate),
    ...(rateCurrency ? { rateCurrency } : {}),
    desiredMonthlyIncome:
      monthlyIncome.trim() === "" ? Number.NaN : Number(monthlyIncome),
    workFormats,
    englishLevel,
  }
  const enabled = freelancerProfileSchema.safeParse(profileCandidate).success

  function changeSpecialization(value: string) {
    suggestionRequestId.current += 1
    setSpecialization(value)
    setSuggestions(null)
    setSuggestionError(null)
    setSuggesting(false)
  }

  async function suggestSkills() {
    const requestId = ++suggestionRequestId.current
    setSuggesting(true)
    setSuggestionError(null)
    setSuggestions(null)
    try {
      const nextSuggestions = await onSuggestSkills({
        specialization: specialization.trim(),
        locale,
      })
      if (requestId === suggestionRequestId.current) {
        setSuggestions(
          nextSuggestions
            .filter(
              (skill) => !normalizedSkills.has(skill.toLowerCase()),
            )
            .slice(0, 10),
        )
      }
    } catch (error) {
      if (requestId === suggestionRequestId.current) {
        setSuggestionError(
          error instanceof Error ? error.message : copy.skillSuggestionsFailed,
        )
      }
    } finally {
      if (requestId === suggestionRequestId.current) setSuggesting(false)
    }
  }

  function addSuggestedSkill(skill: string) {
    setSkills((current) => mergeSkills(current, [...skillInput.split(","), skill]))
    setSkillInput("")
  }

  function commitSkillInput() {
    setSkills((current) => mergeSkills(current, skillInput.split(",")))
    setSkillInput("")
  }

  function removeSkill(skill: string) {
    setSkills((current) => current.filter((value) => value !== skill))
    setSkillLevels((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== skill.toLowerCase())))
  }

  function toggleWorkFormat(format: WorkFormat) {
    setWorkFormats((current) =>
      current.includes(format)
        ? current.filter((value) => value !== format)
        : [...current, format],
    )
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const parsed = freelancerProfileSchema.safeParse(profileCandidate)
    if (parsed.success) onSave(parsed.data)
  }

  return (
    <section className="mx-auto max-w-3xl rounded-3xl border border-border bg-card p-6 shadow-sm sm:p-10">
      <p className="text-sm font-semibold uppercase tracking-[0.16em] text-primary">{copy.profile}</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight">{copy.completeProfileTitle}</h1>
      <p className="mt-3 text-muted-foreground">{copy.completeProfileDescription}</p>
      <form onSubmit={submit} className="mt-8 grid gap-5 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="profile-specialization">{copy.specialization}</Label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input id="profile-specialization" value={specialization} placeholder={copy.specializationPlaceholder} onChange={(event) => changeSpecialization(event.target.value)} />
            <Button type="button" variant="outline" disabled={!specialization.trim() || suggesting} onClick={suggestSkills} className="h-8 sm:min-w-36">
              {suggesting ? copy.suggestingSkills : copy.suggestSkills}
            </Button>
          </div>
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="profile-skills">{copy.skills}</Label>
          <Input id="profile-skills" value={skillInput} placeholder={copy.skillsPlaceholder} onChange={(event) => setSkillInput(event.target.value)} onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || event.keyCode === 229) return
            if (event.key === "Enter") {
              event.preventDefault()
              commitSkillInput()
            }
          }} />
          <p className="text-xs text-muted-foreground">{copy.skillsExample}</p>
          {skills.length ? (
            <div className="space-y-2 pt-2">
              <p className="text-xs text-muted-foreground">{copy.skillLevelsHint}</p>
              {skills.map((skill, index) => {
                const key = skill.toLowerCase()
                return (
                  <div key={key} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2">
                    <Label htmlFor={`skill-level-${index}`}>{copy.skillLevel}: {skill}</Label>
                    <select id={`skill-level-${index}`} value={Object.hasOwn(skillLevels, key) ? skillLevels[key] : ""} onChange={(event) => {
                      const level = event.target.value as SkillLevel | ""
                      setSkillLevels((current) => level
                        ? { ...current, [key]: level }
                        : Object.fromEntries(Object.entries(current).filter(([name]) => name !== key)))
                    }} className="h-9 rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                      <option value="">{copy.skillLevelUnspecified}</option>
                      <option value="primary">{copy.skillLevelPrimary}</option>
                      <option value="confident">{copy.skillLevelConfident}</option>
                      <option value="basic">{copy.skillLevelBasic}</option>
                    </select>
                    <button type="button" onClick={() => removeSkill(skill)} aria-label={`${copy.removeSkill}: ${skill}`} className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground">
                      <X className="size-4" aria-hidden="true" />
                    </button>
                  </div>
                )
              })}
            </div>
          ) : null}
          {visibleSuggestions?.length ? (
            <div className="flex flex-wrap gap-2 pt-1">
              {visibleSuggestions.map((skill) => (
                <Button key={skill} type="button" variant="secondary" size="sm" onClick={() => addSuggestedSkill(skill)}>
                  {skill}
                </Button>
              ))}
            </div>
          ) : suggestions ? (
            <p className="text-sm text-muted-foreground">{copy.noSkillSuggestions}</p>
          ) : null}
          {suggestionError ? <p role="alert" className="text-sm text-danger">{suggestionError}</p> : null}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-experience">{copy.experience}</Label>
          <Input id="profile-experience" type="number" min={0} max={60} value={experience} onChange={(event) => setExperience(event.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-rate">{copy.preferredRate}</Label>
          <div className="relative">
            <Input id="profile-rate" type="number" min={0} step="any" value={rate} onChange={(event) => setRate(event.target.value)} className="pr-16" />
            <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-xs text-muted-foreground">{rateCurrency}{copy.perHour}</span>
          </div>
          <Label htmlFor="profile-rate-currency">{copy.rateCurrency}</Label>
          <select id="profile-rate-currency" value={rateCurrency} onChange={(event) => setRateCurrency(event.target.value as Currency | "")} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm">
            <option value="">{copy.currencyUnspecified}</option>
            {currencies.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-monthly-income">{copy.desiredMonthlyIncome}</Label>
          <div className="relative">
            <Input id="profile-monthly-income" type="number" min={0} step="any" required value={monthlyIncome} onChange={(event) => setMonthlyIncome(event.target.value)} className="pr-20" />
            <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-xs text-muted-foreground">{copy.monthlyCurrency}</span>
          </div>
        </div>
        <fieldset className="space-y-2 sm:col-span-2">
          <legend className="text-sm font-medium">{copy.workFormats}</legend>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {workFormatOptions.map(({ value, label }) => (
              <label key={value} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={workFormats.includes(value)} onChange={() => toggleWorkFormat(value)} className="size-4 accent-primary" />
                {copy[label]}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="profile-english">{copy.englishLevel}</Label>
          <select id="profile-english" value={englishLevel} onChange={(event) => setEnglishLevel(event.target.value as EnglishLevel)} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            {englishLevels.map(({ value, label }) => <option key={value} value={value}>{copy[label]}</option>)}
          </select>
        </div>
        <div className="sm:col-span-2">
          <Button type="submit" disabled={!enabled} className="h-11 w-full sm:w-auto sm:min-w-48">
            {profile ? copy.saveChanges : copy.saveProfile}
          </Button>
        </div>
      </form>
    </section>
  )
}
