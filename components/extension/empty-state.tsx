import { FileSearch } from "lucide-react"

interface EmptyStateProps {
  title: string
  description: string
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 py-12 text-center">
      <div className="mb-4 flex size-16 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
        <FileSearch className="size-7" aria-hidden="true" />
      </div>
      <h2 className="text-[15px] font-semibold">{title}</h2>
      <p className="mt-1.5 max-w-[280px] text-[13px] leading-relaxed text-muted-foreground">
        {description}
      </p>
    </div>
  )
}
