import { Target } from "lucide-react"

interface AppHeaderProps {
  subtitle?: string
}

export function AppHeader({ subtitle }: AppHeaderProps) {
  return (
    <header className="flex items-center gap-2.5 border-b border-border bg-card px-4 py-3">
      <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <Target className="size-4" aria-hidden="true" />
      </div>
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-semibold tracking-tight">FitCheck</span>
        <span className="text-[11px] text-muted-foreground">
          {subtitle ?? "Should you spend connects?"}
        </span>
      </div>
    </header>
  )
}
