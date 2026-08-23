"use client"

import { useState, type KeyboardEvent } from "react"
import { X } from "lucide-react"
import { Input } from "@/components/ui/input"

interface SkillInputProps {
  skills: string[]
  onChange: (skills: string[]) => void
}

export function SkillInput({ skills, onChange }: SkillInputProps) {
  const [value, setValue] = useState("")

  function addSkill() {
    const trimmed = value.trim()
    if (!trimmed) return
    if (!skills.some((s) => s.toLowerCase() === trimmed.toLowerCase())) {
      onChange([...skills, trimmed])
    }
    setValue("")
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault()
      addSkill()
    } else if (e.key === "Backspace" && !value && skills.length) {
      onChange(skills.slice(0, -1))
    }
  }

  function remove(skill: string) {
    onChange(skills.filter((s) => s !== skill))
  }

  return (
    <div className="flex flex-col gap-2">
      {skills.length ? (
        <div className="flex flex-wrap gap-1.5">
          {skills.map((skill) => (
            <span
              key={skill}
              className="inline-flex items-center gap-1 rounded-md bg-secondary py-0.5 pl-2 pr-1 text-xs font-medium text-secondary-foreground"
            >
              {skill}
              <button
                type="button"
                onClick={() => remove(skill)}
                className="flex size-4 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                aria-label={`Remove ${skill}`}
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <Input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={addSkill}
        placeholder="Type a skill and press Enter"
      />
    </div>
  )
}
