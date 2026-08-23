import { createOpenRouterTransport } from "@/lib/analysis/openrouter"
import { corsHeaders, createAnalyzeHandler, json } from "./handler"

function allowedOrigins() {
  return (process.env.ALLOWED_ORIGINS ?? "http://localhost:3000")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean)
}

export async function POST(request: Request) {
  const apiKey = process.env.OPENROUTER_API_KEY
  if (!apiKey) return json({ error: "server_not_configured" }, 503)
  const handler = createAnalyzeHandler({
    allowedOrigins: allowedOrigins(),
    transport: createOpenRouterTransport({
      apiKey,
      model: process.env.OPENROUTER_MODEL,
    }),
  })
  return handler(request)
}

export async function OPTIONS(request: Request) {
  const origin = request.headers.get("origin") ?? ""
  if (!allowedOrigins().includes(origin)) {
    return json({ error: "origin_not_allowed" }, 403)
  }
  return new Response(null, { status: 204, headers: corsHeaders(origin) })
}
