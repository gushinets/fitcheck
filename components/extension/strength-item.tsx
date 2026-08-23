import { Check } from "lucide-react"

export function StrengthItem({ text }: { text: string }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full bg-success-muted text-success">
        <Check className="size-3" strokeWidth={3} aria-hidden="true" />
      </span>
      <span className="text-[13px] leading-snug text-foreground">{text}</span>
    </li>
  )
}
