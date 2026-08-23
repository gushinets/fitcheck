import { Zap } from "lucide-react"
import { Button } from "@/components/ui/button"
import { messages, type Messages } from "@/lib/i18n/messages"

interface AnalyzeButtonProps {
  onClick: () => void
  copy?: Messages
}

export function AnalyzeButton({ onClick, copy = messages.en }: AnalyzeButtonProps) {
  return (
    <div className="flex flex-col gap-2">
      <Button onClick={onClick} className="h-11 w-full text-sm font-semibold">
        <Zap className="size-4" aria-hidden="true" />
        {copy.analyzeJob}
      </Button>
      <p className="text-center text-[11px] leading-relaxed text-muted-foreground">
        {copy.compareHint}
      </p>
    </div>
  )
}
