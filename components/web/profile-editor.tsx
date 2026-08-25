"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { freelancerProfileSchema } from "@/lib/analysis/schema"
import type { WebMessages } from "@/lib/i18n/web-messages"
import type { EnglishLevel, FreelancerProfile } from "@/lib/types"

const englishLevels: EnglishLevel[] = [
  "Basic",
  "Intermediate",
  "Upper Intermediate",
  "Advanced",
  "Fluent",
]

export function ProfileEditor({
  profile,
  copy,
  onSave,
}: {
  profile: FreelancerProfile | null
  copy: WebMessages
  onSave: (profile: FreelancerProfile) => void
}) {
  const [specialization, setSpecialization] = useState(profile?.specialization ?? "")
  const [skills, setSkills] = useState(profile?.skills.join(", ") ?? "")
  const [experience, setExperience] = useState(String(profile?.experienceYears ?? 0))
  const [rate, setRate] = useState(String(profile?.preferredRate ?? 0))
  const [englishLevel, setEnglishLevel] = useState<EnglishLevel>(profile?.englishLevel ?? "Intermediate")
  const parsedSkills = skills.split(",").map((skill) => skill.trim()).filter(Boolean)
  const enabled = Boolean(specialization.trim() && parsedSkills.length)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const parsed = freelancerProfileSchema.safeParse({
      specialization,
      skills: parsedSkills,
      experienceYears: Number(experience),
      preferredRate: Number(rate),
      englishLevel,
    })
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
          <Input id="profile-specialization" value={specialization} placeholder={copy.specializationPlaceholder} onChange={(event) => setSpecialization(event.target.value)} />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="profile-skills">{copy.skills}</Label>
          <Input id="profile-skills" value={skills} placeholder={copy.skillsPlaceholder} onChange={(event) => setSkills(event.target.value)} />
          <p className="text-xs text-muted-foreground">TypeScript, React, PostgreSQL</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-experience">{copy.experience}</Label>
          <Input id="profile-experience" type="number" min={0} max={60} value={experience} onChange={(event) => setExperience(event.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-rate">{copy.preferredRate}</Label>
          <Input id="profile-rate" type="number" min={0} max={1000} value={rate} onChange={(event) => setRate(event.target.value)} />
        </div>
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="profile-english">{copy.englishLevel}</Label>
          <select id="profile-english" value={englishLevel} onChange={(event) => setEnglishLevel(event.target.value as EnglishLevel)} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
            {englishLevels.map((level) => <option key={level}>{level}</option>)}
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
