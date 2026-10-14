import { after } from "next/server"
import { beginWebsiteOperation } from "@/lib/metrics/operations"
import { fetchPublicPage } from "@/lib/extraction/network"
import { createExtractHandler } from "./handler"

export const runtime = "nodejs"

const handler = createExtractHandler({ fetchPage: fetchPublicPage })

export async function POST(request: Request) {
  const operation = beginWebsiteOperation(request, "extraction", after)
  const response = await handler(request)
  return operation?.complete(response) ?? response
}
