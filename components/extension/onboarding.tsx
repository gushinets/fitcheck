"use client"

import { Target } from "lucide-react"
import { ProfileForm } from "./profile-form"
import { defaultProfile } from "@/lib/mock-data"
import type { FreelancerProfile } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"

interface OnboardingProps {
  onSave: (profile: FreelancerProfile) => void
  copy?: Messages
}

const emptyProfile: FreelancerProfile = {
  specialization: "",
  skills: [],
  experienceYears: 0,
  preferredRate: 0,
  workFormats: ["remote"],
  englishLevel: "Upper Intermediate",
}

export function Onboarding({ onSave, copy = messages.en }: OnboardingProps) {
  return (
    <div className="flex flex-1 flex-col overflow-y-auto px-4 py-5">
      <div className="mb-5 flex flex-col items-center text-center">
        <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Target className="size-5" aria-hidden="true" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight">
          {copy.onboardingTitle}
        </h1>
        <p className="mt-1 max-w-[300px] text-[13px] leading-relaxed text-muted-foreground text-pretty">
          {copy.onboardingDescription}
        </p>
      </div>

      <ProfileForm
        initial={emptyProfile}
        submitLabel={copy.saveProfile}
        copy={copy}
        onSubmit={onSave}
      />

      <button
        type="button"
        onClick={() => onSave(defaultProfile)}
        className="mt-4 text-center text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        {copy.useSampleProfile}
      </button>
    </div>
  )
}
