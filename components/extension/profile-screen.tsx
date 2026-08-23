"use client"

import { ProfileForm } from "./profile-form"
import type { FreelancerProfile } from "@/lib/types"
import { messages, type Messages } from "@/lib/i18n/messages"

interface ProfileScreenProps {
  profile: FreelancerProfile
  onSave: (profile: FreelancerProfile) => void
  onReset: () => void
  copy?: Messages
}

export function ProfileScreen({ profile, onSave, onReset, copy = messages.en }: ProfileScreenProps) {
  return (
    <div className="flex flex-1 flex-col overflow-y-auto px-4 py-4">
      <h2 className="mb-3 text-[13px] font-semibold text-muted-foreground">
        {copy.profileTitle}
      </h2>
      <ProfileForm
        key={JSON.stringify(profile)}
        initial={profile}
        submitLabel={copy.saveChanges}
        copy={copy}
        onSubmit={onSave}
        onReset={onReset}
      />
    </div>
  )
}
