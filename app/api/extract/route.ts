import { fetchPublicPage } from "@/lib/extraction/network"
import { createExtractHandler } from "./handler"

export const runtime = "nodejs"

const handler = createExtractHandler({ fetchPage: fetchPublicPage })

export async function POST(request: Request) {
  return handler(request)
}
