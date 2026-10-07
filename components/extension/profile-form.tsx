"use client"

import { useState } from "react"
import { RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { SkillInput } from "./skill-input"
import type { EnglishLevel, FreelancerProfile } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"

const englishLevels: EnglishLevel[] = [
  "Basic",
  "Intermediate",
  "Upper Intermediate",
  "Advanced",
  "Fluent",
]

interface ProfileFormProps {
  initial: FreelancerProfile
  submitLabel: string
  onSubmit: (profile: FreelancerProfile) => void
  onReset?: () => void
  copy?: Messages
}

export function ProfileForm({
  initial,
  submitLabel,
  onSubmit,
  onReset,
  copy = messages.en,
}: ProfileFormProps) {
  const [specialization, setSpecialization] = useState(initial.specialization)
  const [skills, setSkills] = useState<string[]>(initial.skills)
  const [experienceYears, setExperienceYears] = useState(
    String(initial.experienceYears),
  )
  const [preferredRate, setPreferredRate] = useState(String(initial.preferredRate))
  const [englishLevel, setEnglishLevel] = useState<EnglishLevel>(
    initial.englishLevel,
  )

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!specialization.trim() || skills.length === 0) return
    onSubmit({
      specialization: specialization.trim(),
      skills,
      ...(initial.skillLevels ? {
        skillLevels: Object.fromEntries(Object.entries(initial.skillLevels).filter(
          ([key]) => skills.some((skill) => skill.trim().toLowerCase() === key),
        )),
      } : {}),
      experienceYears: Number(experienceYears) || 0,
      preferredRate: Number(preferredRate) || 0,
      desiredMonthlyIncome: initial.desiredMonthlyIncome,
      workFormats: initial.workFormats,
      englishLevel,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="specialization">{copy.specialization}</Label>
        <Input
          id="specialization"
          required
          value={specialization}
          onChange={(e) => setSpecialization(e.target.value)}
          placeholder="e.g. Backend Developer"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>{copy.skills}</Label>
        <SkillInput skills={skills} onChange={setSkills} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="experience">{copy.experience}</Label>
          <div className="relative">
            <Input
              id="experience"
              inputMode="numeric"
              value={experienceYears}
              onChange={(e) =>
                setExperienceYears(e.target.value.replace(/[^0-9]/g, ""))
              }
              className="pr-12"
            />
            <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-xs text-muted-foreground">
              {copy.years}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rate">{copy.preferredRate}</Label>
          <div className="relative">
            <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-xs text-muted-foreground">
              $
            </span>
            <Input
              id="rate"
              inputMode="numeric"
              value={preferredRate}
              onChange={(e) =>
                setPreferredRate(e.target.value.replace(/[^0-9]/g, ""))
              }
              className="pl-6 pr-10"
            />
            <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-xs text-muted-foreground">
              /hr
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>{copy.englishLevel}</Label>
        <Select
          value={englishLevel}
          onValueChange={(v) => setEnglishLevel(v as EnglishLevel)}
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {englishLevels.map((level) => (
              <SelectItem key={level} value={level}>
                {level}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mt-1 flex flex-col gap-2">
        <Button
          type="submit"
          disabled={!specialization.trim() || skills.length === 0}
          className="h-11 w-full text-sm font-semibold"
        >
          {submitLabel}
        </Button>
        {onReset ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onReset}
            className="h-9 w-full text-muted-foreground"
          >
            <RotateCcw className="size-4" aria-hidden="true" />
            {copy.resetProfile}
          </Button>
        ) : null}
      </div>
    </form>
  )
}
