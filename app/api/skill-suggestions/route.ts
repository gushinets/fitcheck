import { isSupportedOpenAIModel } from "@/lib/openai/client"
import { after } from "next/server"
import { beginWebsiteOperation } from "@/lib/metrics/operations"
import { createOpenAISkillSuggestionTransport } from "@/lib/skill-suggestions/openai"
import { corsHeaders, createSkillSuggestionsHandler, json } from "./handler"

function allowedOrigins() {
  return (process.env.ALLOWED_ORIGINS ?? "http://localhost:3000")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean)
}

export async function POST(request: Request) {
  const origins = allowedOrigins()
  const origin = request.headers.get("origin") ?? ""
  const requestOrigin = new URL(request.url).origin
  if (origin && origin !== requestOrigin && !origins.includes(origin)) {
    return json({ error: "origin_not_allowed" }, 403)
  }

  const apiKey = process.env.OPEN_AI_KEY
  if (!apiKey || !isSupportedOpenAIModel(process.env.OPEN_AI_MODEL)) return json({ error: "server_not_configured" }, 503)

  const operation = beginWebsiteOperation(request, "suggestions", after)
  const handler = createSkillSuggestionsHandler({
    allowedOrigins: origins,
    transport: createOpenAISkillSuggestionTransport({
      apiKey,
      model: process.env.OPEN_AI_MODEL,
      operation: operation?.context,
      attemptSink: operation?.sink,
    }),
  })
  const response = await handler(request)
  return operation?.complete(response) ?? response
}

export async function OPTIONS(request: Request) {
  const origin = request.headers.get("origin") ?? ""
  const requestOrigin = new URL(request.url).origin
  if (origin !== requestOrigin && !allowedOrigins().includes(origin)) {
    return json({ error: "origin_not_allowed" }, 403)
  }

  return new Response(null, { status: 204, headers: corsHeaders(origin) })
}
