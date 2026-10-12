import { describe, expect, it } from "vitest"
import { z } from "zod"
import { BackendApiError, BackendTransportError, createBackendClient } from "./client"

const success = z.object({ status: z.literal("ok") }).parse
const reply = (response: Response) => async () => response

describe("backend transport", () => {
  it("validates JSON success", async () => {
    const client = createBackendClient({ baseUrl: "/backend/v1", fetch: reply(Response.json({ status: "ok" })) })
    expect(await client.request("health", { validate: success })).toEqual({ status: "ok" })
  })
  it("passes undefined to validator for 204", async () => {
    const client = createBackendClient({ baseUrl: "/backend/v1", fetch: reply(new Response(null, { status: 204 })) })
    expect(await client.request("draft", { method: "DELETE", validate: z.undefined().parse })).toBeUndefined()
  })
  it("parses API error and header request ID fallback", async () => {
    for (const requestId of ["r-body", undefined]) {
      const client = createBackendClient({ baseUrl: "/backend/v1", fetch: reply(Response.json({ error: { code: "conflict", message: "Conflict", requestId, details: [] } }, { status: 409, headers: { "X-Request-ID": "r-header" } })) })
      const error = await client.request("profile", { validate: success }).catch((error: unknown) => error)
      expect(error).toBeInstanceOf(BackendApiError)
      expect(error).toMatchObject({ status: 409, code: "conflict", requestId: requestId ?? "r-header" })
    }
  })
  it("rejects malformed error responses", async () => {
    for (const response of [new Response("bad", { status: 502 }), Response.json({ error: { code: 1 } }, { status: 400 })]) {
      const client = createBackendClient({ baseUrl: "/backend/v1", fetch: reply(response) })
      await expect(client.request("profile", { validate: success })).rejects.toBeInstanceOf(BackendTransportError)
    }
  })
  it("rejects malformed success JSON", async () => {
    const client = createBackendClient({ baseUrl: "/backend/v1", fetch: reply(new Response("bad")) })
    await expect(client.request("profile", { validate: success })).rejects.toMatchObject({ reason: "invalid_json" })
  })
  it("rejects invalid success payload", async () => {
    const client = createBackendClient({ baseUrl: "/backend/v1", fetch: reply(Response.json({ status: "fake" })) })
    await expect(client.request("profile", { validate: success })).rejects.toMatchObject({ reason: "invalid_response" })
  })
  it("preserves AbortSignal cancellation", async () => {
    const controller = new AbortController()
    controller.abort()
    const client = createBackendClient({ baseUrl: "https://api.example/v1", fetch: async (_url, init) => { init?.signal?.throwIfAborted(); return Response.json({ status: "ok" }) } })
    await expect(client.request("jobs", { signal: controller.signal, validate: success })).rejects.toMatchObject({ name: "AbortError" })
  })
  it("joins base URL and carries JSON credentials and headers", async () => {
    const observed: { url: string; init?: RequestInit }[] = []
    const transport: typeof fetch = async (url, init) => { observed.push({ url: String(url), init }); return Response.json({ status: "ok" }) }
    const client = createBackendClient({ baseUrl: "https://api.example/v1/", fetch: transport, credentials: "omit" })
    await client.request("/profile", { method: "PUT", body: { expectedRevision: "r1" }, headers: { Authorization: "Bearer test-session", "Idempotency-Key": "id1" }, validate: success })
    expect(observed[0].url).toBe("https://api.example/v1/profile")
    expect(observed[0].init?.credentials).toBe("omit")
    expect(observed[0].init?.body).toBe('{"expectedRevision":"r1"}')
    expect(new Headers(observed[0].init?.headers).get("Authorization")).toBe("Bearer test-session")
    expect(new Headers(observed[0].init?.headers).get("Content-Type")).toBe("application/json")
    await createBackendClient({ baseUrl: "/backend/v1", fetch: transport }).request("profile", { validate: success })
    expect(observed[1].url).toBe("/backend/v1/profile")
    expect(observed[1].init?.credentials).toBe("same-origin")
  })
  it("does not forward credentials to absolute foreign routes", async () => {
    const client = createBackendClient({ baseUrl: "/backend/v1", fetch: async () => { throw new Error("must not send") } })
    for (const route of ["https://evil.test/x", "//evil.test/x", "../auth", "profile/../../auth", "profile\\..\\auth"]) {
      await expect(client.request(route, { validate: success })).rejects.toMatchObject({ reason: "invalid_path" })
    }
  })
  it("does not retry network failure or wrap it as API error", async () => {
    let calls = 0
    const client = createBackendClient({ baseUrl: "/backend/v1", fetch: async () => { calls++; throw new TypeError("network") } })
    await expect(client.request("analysis-jobs", { method: "POST", validate: success })).rejects.toMatchObject({ reason: "network" })
    expect(calls).toBe(1)
  })
})
