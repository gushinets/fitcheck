import { after } from "next/server"
import { beginWebsiteOperation } from "@/lib/metrics/operations"
import { createDeepSeekTransport } from "@/lib/analysis/deepseek"
import { corsHeaders, createAnalyzeHandler, json } from "./handler"

function allowedOrigins() {
  return (process.env.ALLOWED_ORIGINS ?? "http://localhost:3000")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean)
}

export async function POST(request: Request) {
  const apiKey = process.env.DEEPSEEK_API_KEY
  if (!apiKey) return json({ error: "server_not_configured" }, 503)
  const operation = beginWebsiteOperation(request, "analysis", after)
  const handler = createAnalyzeHandler({
    allowedOrigins: allowedOrigins(),
    transport: createDeepSeekTransport({
      apiKey,
      model: process.env.DEEPSEEK_MODEL,
      metrics: operation ?? undefined,
    }),
  })
  const response = await handler(request)
  return operation?.complete(response) ?? response
}

export async function OPTIONS(request: Request) {
  const origin = request.headers.get("origin") ?? ""
  if (!allowedOrigins().includes(origin)) {
    return json({ error: "origin_not_allowed" }, 403)
  }
  return new Response(null, { status: 204, headers: corsHeaders(origin) })
}
