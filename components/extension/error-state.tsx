import { RefreshCw, TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { messages, type Messages } from "@/lib/i18n/messages"

interface ErrorStateProps {
  onRetry: () => void
  onReport?: () => void
  copy?: Messages
}

export function ErrorState({ onRetry, onReport, copy = messages.en }: ErrorStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-12 text-center">
      <div className="mb-4 flex size-16 items-center justify-center rounded-2xl bg-warning-muted text-warning">
        <TriangleAlert className="size-7" aria-hidden="true" />
      </div>
      <h2 className="text-[15px] font-semibold">{copy.errorTitle}</h2>
      <p className="mt-1.5 max-w-[280px] text-[13px] leading-relaxed text-muted-foreground">
        {copy.errorDescription}
      </p>
      <div className="mt-6 flex w-full max-w-[240px] flex-col gap-2">
        <Button onClick={onRetry} className="h-10 w-full">
          <RefreshCw className="size-4" aria-hidden="true" />
          {copy.retry}
        </Button>
        <Button variant="ghost" onClick={onReport} className="h-9 w-full">
          {copy.reportProblem}
        </Button>
      </div>
    </div>
  )
}
