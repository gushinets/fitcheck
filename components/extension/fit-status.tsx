import { CircleCheck, CircleAlert } from "lucide-react"
import type { FitStatus as Status } from "@/lib/types"
import { cn } from "@/lib/utils"

interface FitStatusProps {
  status: Status
  label: string
}

export function FitStatus({ status, label }: FitStatusProps) {
  const isGo = status === "GO"
  const Icon = isGo ? CircleCheck : CircleAlert

  return (
    <div className="flex flex-col items-center gap-1.5">
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-base font-bold uppercase tracking-wide",
          isGo
            ? "bg-success text-success-foreground"
            : "bg-danger text-danger-foreground",
        )}
      >
        <Icon className="size-4" aria-hidden="true" />
        {isGo ? "GO" : "NO-GO"}
      </span>
      <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
    </div>
  )
}
