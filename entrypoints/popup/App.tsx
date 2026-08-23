import { ExtensionApp } from "@/components/extension/extension-app"
import { createBrowserRuntime } from "@/lib/extension/browser-adapter"
import type { ExtensionRuntime } from "@/lib/extension/runtime"

interface AppProps {
  runtime?: ExtensionRuntime
}

export function App({ runtime }: AppProps) {
  const activeRuntime = runtime ?? createBrowserRuntime(
    import.meta.env.WXT_PUBLIC_API_BASE_URL ?? "http://localhost:3000",
  )
  return <ExtensionApp runtime={activeRuntime} />
}
