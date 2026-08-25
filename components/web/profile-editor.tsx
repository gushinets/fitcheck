"use client"

import { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { freelancerProfileSchema } from "@/lib/analysis/schema"
import type { WebMessages } from "@/lib/i18n/web-messages"
import type { SkillSuggestionRequest } from "@/lib/skill-suggestions/schema"
import type {
  EnglishLevel,
  FreelancerProfile,
  Locale,
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
  const [skills, setSkills] = useState(profile?.skills.join(", ") ?? "")
  const [experience, setExperience] = useState(String(profile?.experienceYears ?? 0))
  const [rate, setRate] = useState(String(profile?.preferredRate ?? 0))
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
  const parsedSkills = skills.split(",").map((skill) => skill.trim()).filter(Boolean)
  const normalizedSkills = new Set(
    parsedSkills.map((skill) => skill.toLocaleLowerCase()),
  )
  const visibleSuggestions = suggestions?.filter(
    (skill) => !normalizedSkills.has(skill.toLocaleLowerCase()),
  )
  const profileCandidate = {
    specialization,
    skills: parsedSkills,
    experienceYears: Number(experience),
    preferredRate: Number(rate),
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
        setSuggestions(nextSuggestions)
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
    setSkills((current) => {
      if (!current.trim()) return skill
      if (/[,]\s*$/.test(current)) return `${current} ${skill}`
      return `${current}, ${skill}`
    })
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
          <Input id="profile-skills" value={skills} placeholder={copy.skillsPlaceholder} onChange={(event) => setSkills(event.target.value)} />
          <p className="text-xs text-muted-foreground">{copy.skillsExample}</p>
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
            <Input id="profile-rate" type="number" min={0} value={rate} onChange={(event) => setRate(event.target.value)} className="pr-16" />
            <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-xs text-muted-foreground">{copy.hourlyCurrency}</span>
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-monthly-income">{copy.desiredMonthlyIncome}</Label>
          <div className="relative">
            <Input id="profile-monthly-income" type="number" min={0} required value={monthlyIncome} onChange={(event) => setMonthlyIncome(event.target.value)} className="pr-20" />
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
