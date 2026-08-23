"use client"

import { ExtensionApp } from "@/components/extension/extension-app"
import { createPreviewRuntime } from "@/lib/extension/preview-adapter"

const runtime = createPreviewRuntime()

export default function Page() {
  return <ExtensionApp runtime={runtime} previewControls />
}
