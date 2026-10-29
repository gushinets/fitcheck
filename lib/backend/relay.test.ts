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

it.each([undefined, "false", "TRUE"])("does not forward caller IP headers without explicit ingress trust (%s)", async trust => {
  vi.stubEnv("FITCHECK_TRUST_PROXY_HEADERS", trust)
  const upstream = vi.fn(async () => new Response(null, { status: 204 }))
  await relayBackend(new Request(`${origin}/api/backend/v1/auth/csrf`, { headers: {
    "x-forwarded-for": "198.51.100.9, 203.0.113.5", "x-real-ip": "198.51.100.9", forwarded: "for=198.51.100.9",
  } }), "https://backend.test", upstream)
  const headers = new Headers((upstream.mock.calls[0] as unknown as [string, RequestInit])[1].headers)
  for (const name of ["x-forwarded-for", "x-real-ip", "forwarded"]) expect(headers.has(name)).toBe(false)
})

it.each(["203.0.113.5", "2001:db8::5"])("forwards only the ingress-appended visitor IP (%s)", async ip => {
  vi.stubEnv("FITCHECK_TRUST_PROXY_HEADERS", "true")
  const upstream = vi.fn(async () => new Response(null, { status: 204 }))
  await relayBackend(new Request(`${origin}/api/backend/v1/auth/csrf`, { headers: {
    "x-forwarded-for": `198.51.100.9, ${ip}`, "x-real-ip": "198.51.100.9", forwarded: "for=198.51.100.9",
  } }), "https://backend.test", upstream)
  const headers = new Headers((upstream.mock.calls[0] as unknown as [string, RequestInit])[1].headers)
  expect(headers.get("x-forwarded-for")).toBe(ip)
  expect(headers.has("x-real-ip")).toBe(false)
  expect(headers.has("forwarded")).toBe(false)
})

it.each([undefined, "", "unknown", "203.0.113.5,", "203.0.113.5, forged", "203.0.113.5:443", "[2001:db8::5]"])(
  "refuses an absent or invalid ingress IP when forwarding is enabled (%s)", async forwarded => {
    vi.stubEnv("FITCHECK_TRUST_PROXY_HEADERS", "true")
    const upstream = vi.fn()
    const response = await relayBackend(new Request(`${origin}/api/backend/v1/auth/csrf`, {
      headers: forwarded === undefined ? {} : { "x-forwarded-for": forwarded },
    }), "https://backend.test", upstream)
    expect(response.status).toBe(503)
    expect(upstream).not.toHaveBeenCalled()
  },
)

it("preserves separate visitor IPs through the same relay", async () => {
  vi.stubEnv("FITCHECK_TRUST_PROXY_HEADERS", "true")
  const upstream = vi.fn(async () => new Response(null, { status: 204 }))
  for (const ip of ["203.0.113.5", "203.0.113.6"]) {
    await relayBackend(new Request(`${origin}/api/backend/v1/auth/csrf`, {
      headers: { "x-forwarded-for": ip },
    }), "https://backend.test", upstream)
  }
  expect(upstream.mock.calls.map(call => new Headers((call as unknown as [string, RequestInit])[1].headers).get("x-forwarded-for")))
    .toEqual(["203.0.113.5", "203.0.113.6"])
})

it('attests an existing visitor only on auth/claim routes and strips caller identity headers', async () => {
  const { resolveVisitor, VISITOR_COOKIE } = await import('@/lib/metrics/cookie')
  const { createHmac } = await import('node:crypto')
  vi.stubEnv('METRICS_COOKIE_SECRET', 'cookie-secret')
  vi.stubEnv('METRICS_BRIDGE_KEY', 'bridge-secret')
  vi.stubEnv('METRICS_ENVIRONMENT', 'test')
  const visitor = resolveVisitor(undefined, 'cookie-secret', Date.now() - 1000)!
  const upstream = vi.fn(async () => new Response(null, { status: 204 }))
  async function call(path: string, cookie?: string) {
    await relayBackend(new Request(`${origin}/api/backend/${path}`, { method: 'POST', headers: {
      origin, ...(cookie ? { cookie } : {}), 'x-fitcheck-visitor-proof': 'forged', 'x-fitcheck-metrics-key': 'forged',
    }, body: '{}' }), 'https://backend.test', upstream)
    return new Headers((upstream.mock.calls.at(-1) as unknown as [string, RequestInit])[1].headers)
  }
  const cookie = `${VISITOR_COOKIE}=${visitor.cookieValue}`
  for (const path of ['v1/auth/register', 'v1/auth/login', 'v1/guest-claims']) {
    const headers = await call(path, cookie)
    const proof = headers.get('x-fitcheck-visitor-proof')!
    expect(proof).toBeTruthy()
    const [encoded, mac] = proof.split('.')
    expect(mac).toBe(createHmac('sha256', 'bridge-secret').update('fitcheck:metrics:identity:v1:' + encoded).digest('base64url'))
    expect(JSON.parse(Buffer.from(encoded, 'base64url').toString())).toMatchObject({ v: 1, environment: 'test', visitorId: visitor.visitorId, path: '/' + path, method: 'POST' })
    expect(headers.get('x-fitcheck-metrics-key')).toBeNull()
    expect(headers.get('cookie')).toBeNull()
  }
  for (const value of [undefined, `${VISITOR_COOKIE}=forged`, `${cookie}; ${cookie}`]) {
    expect((await call('v1/auth/login', value)).get('x-fitcheck-visitor-proof')).toBeNull()
  }
  expect((await call('v1/profile', cookie)).get('x-fitcheck-visitor-proof')).toBeNull()
})

it('does not attest an expired visitor or when analytics configuration is absent', async () => {
  const { visitorProof } = await import('@/lib/metrics/identity-proof')
  const { resolveVisitor, VISITOR_COOKIE, VISITOR_LIFETIME_MS } = await import('@/lib/metrics/cookie')
  const now=Date.now(); const visitor=resolveVisitor(undefined,'secret',now-VISITOR_LIFETIME_MS)!
  const request=new Request(`${origin}/api/backend/v1/auth/login`,{method:'POST',headers:{cookie:`${VISITOR_COOKIE}=${visitor.cookieValue}`}})
  expect(visitorProof(request,'/v1/auth/login',{cookieSecret:'secret',bridgeKey:'bridge',environment:'test'},now)).toBeUndefined()
  expect(visitorProof(request,'/v1/auth/login',{},now)).toBeUndefined()
})
