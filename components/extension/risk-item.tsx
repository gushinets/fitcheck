import { TriangleAlert } from "lucide-react"

export function RiskItem({ text }: { text: string }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full bg-warning-muted text-warning">
        <TriangleAlert className="size-2.5" strokeWidth={2.5} aria-hidden="true" />
      </span>
      <span className="text-[13px] leading-snug text-foreground">{text}</span>
    </li>
  )
}
