import { z } from "zod"
import type { components } from "./generated/schema"

type ErrorDetail = components["schemas"]["ErrorDetail"]
const detailSchema: z.ZodType<ErrorDetail> = z.object({
  location: z.array(z.union([z.string(), z.number().int()])),
  code: z.string(),
})
const errorSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
    requestId: z.string().min(1).optional(),
    details: z.array(detailSchema),
  }),
})

export class BackendApiError extends Error {
  readonly name = "BackendApiError"
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId: string | undefined,
    public readonly details: ErrorDetail[],
  ) { super(message) }
}

export class BackendTransportError extends Error {
  readonly name = "BackendTransportError"
  constructor(public readonly reason: "invalid_path" | "network" | "invalid_json" | "invalid_error" | "invalid_response") {
    super(`Backend transport failed: ${reason}`)
  }
}

function routePath(path: string): string {
  if (!path || path.startsWith("//") || /^[a-z][a-z\d+.-]*:/i.test(path) || /[\\#\u0000-\u0020]/.test(path)) {
    throw new BackendTransportError("invalid_path")
  }
  const pathname = path.split("?", 1)[0]
  for (const segment of pathname.split("/")) {
    let decoded: string
    try { decoded = decodeURIComponent(segment) } catch { throw new BackendTransportError("invalid_path") }
    if (decoded === "." || decoded === ".." || /[\\/]/.test(decoded)) throw new BackendTransportError("invalid_path")
  }
  return path.replace(/^\//, "")
}

export function createBackendClient(config: {
  baseUrl: string
  fetch?: typeof fetch
  credentials?: RequestCredentials
}) {
  const transport = config.fetch ?? globalThis.fetch
  const base = config.baseUrl.replace(/\/+$/, "")
  return {
    async request<T>(path: string, options: {
      method?: string
      body?: unknown
      signal?: AbortSignal
      headers?: HeadersInit
      validate: (value: unknown) => T
    }): Promise<T> {
      const url = `${base}/${routePath(path)}`
      const headers = new Headers(options.headers)
      headers.set("Accept", "application/json")
      if (options.body !== undefined) headers.set("Content-Type", "application/json")
      let response: Response
      try {
        response = await transport(url, {
          method: options.method ?? "GET",
          headers,
          body: options.body === undefined ? undefined : JSON.stringify(options.body),
          credentials: config.credentials ?? "same-origin",
          signal: options.signal,
          redirect: "error",
        })
      } catch (error) {
        if (options.signal?.aborted || (error instanceof Error && error.name === "AbortError")) throw error
        throw new BackendTransportError("network")
      }
      let payload: unknown
      if (response.status !== 204) {
        try { payload = await response.json() } catch (error) {
          if (options.signal?.aborted || (error instanceof Error && error.name === "AbortError")) throw error
          throw new BackendTransportError(response.ok ? "invalid_json" : "invalid_error")
        }
      }
      if (!response.ok) {
        const parsed = errorSchema.safeParse(payload)
        if (!parsed.success) throw new BackendTransportError("invalid_error")
        const { code, message, requestId, details } = parsed.data.error
        throw new BackendApiError(response.status, code, message, requestId ?? response.headers.get("X-Request-ID") ?? undefined, details)
      }
      try { return options.validate(payload) } catch { throw new BackendTransportError("invalid_response") }
    },
  }
}
