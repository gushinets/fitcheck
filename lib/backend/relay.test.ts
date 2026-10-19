// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest"
import { relayBackend } from "./relay"

afterEach(() => vi.unstubAllEnvs())
const origin = "https://fitcheck.test"
it("relays session cookies, CSRF and idempotency without forwarding service or browser bearer credentials", async () => {
  const upstream = vi.fn(async () => new Response(null, { status: 204, headers: { "set-cookie": "__Host-fitcheck_session=new; Path=/; Secure; HttpOnly; SameSite=Lax" } }))
  const response = await relayBackend(new Request(`${origin}/api/backend/v1/auth/login`, { method: "POST", headers: {
    origin, cookie: "__Host-fitcheck_session=old; unrelated=private", authorization: "Bearer private", "x-csrf-token": "proof", "idempotency-key": "job-key", "content-type": "application/json",
  }, body: "{}" }), "https://backend.test", upstream)
  expect(response.status).toBe(204)
  expect(response.headers.getSetCookie()).toHaveLength(1)
  const [url, init] = upstream.mock.calls[0] as unknown as [string, RequestInit]
  const headers = new Headers(init.headers)
  expect(url).toBe("https://backend.test/v1/auth/login")
  expect(headers.get("cookie")).toBe("__Host-fitcheck_session=old")
  expect(headers.get("authorization")).toBeNull()
  expect(headers.get("x-csrf-token")).toBe("proof")
  expect(headers.get("idempotency-key")).toBe("job-key")
  expect(init.redirect).toBe("error")
  expect(response.headers.get("cache-control")).toBe("no-store")
})
it.each(["https://evil.test", null])("refuses mutations with untrusted or absent origin (%s)", async foreign => {
  const upstream = vi.fn()
  const response = await relayBackend(new Request(`${origin}/api/backend/v1/profile`, { method: "PUT", headers: foreign ? { origin: foreign } : {} }), "https://backend.test", upstream)
  expect(response.status).toBe(403); expect(upstream).not.toHaveBeenCalled()
})
it("supplies trusted Origin to bootstrap GET when the browser omits it", async () => {
  const upstream = vi.fn(async () => Response.json({ csrfToken: "proof" }))
  await relayBackend(new Request(`${origin}/api/backend/v1/auth/csrf`), "https://backend.test", upstream)
  const init = (upstream.mock.calls[0] as unknown as [string, RequestInit])[1]
  expect(new Headers(init.headers).get("origin")).toBe(origin)
})
it("does not turn a cross-site GET into an authorized bootstrap request", async () => {
  const upstream = vi.fn()
  expect((await relayBackend(new Request(`${origin}/api/backend/v1/auth/csrf`, { headers: { "sec-fetch-site": "cross-site" } }), "https://backend.test", upstream)).status).toBe(403)
  expect(upstream).not.toHaveBeenCalled()
})
it("fails closed when the backend is absent or unreachable", async () => {
  const request = new Request(`${origin}/api/backend/v1/auth/session`)
  expect((await relayBackend(request, "")).status).toBe(503)
  expect((await relayBackend(request, "https://backend.test", async () => { throw new Error("offline") })).status).toBe(503)
})
