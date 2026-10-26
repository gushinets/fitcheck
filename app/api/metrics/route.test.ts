import { describe, expect, it, vi } from 'vitest'
import { createMetricsHandlers } from './handler'
import { resolveVisitor, VISITOR_COOKIE, VISITOR_LIFETIME_MS } from '@/lib/metrics/cookie'
const origin = 'https://website.example'
const event = () => ({ eventId: crypto.randomUUID(), name: 'page_viewed', schemaVersion: 1, occurredAt: new Date().toISOString(), sessionId: crypto.randomUUID(), properties: {} })
const request = (body: unknown, headers: Record<string, string> = {}, method = 'POST') => new Request(`${origin}/api/metrics`, { method, headers: { origin, 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) })
const setup = () => {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, options?: RequestInit) => options?.method === 'DELETE' ? Response.json({deleted:0}) : Response.json({accepted:JSON.parse(String(options?.body)).events.length,duplicates:0}))
  const handlers = createMetricsHandlers({ secret: 'test-secret', allowedOrigins: [origin], bridge: { backendUrl: 'https://collector.example', bridgeKey: 'secret', environment: 'development', runtime: 'production' }, fetchImpl: fetcher })
  return { ...handlers, fetcher }
}
describe('browser metrics boundary', () => {
  it.each(['POST', 'DELETE'] as const)('accepts same-public-host %s behind a TLS terminating proxy', async method => {
    const handlers = setup()
    const visitor = resolveVisitor(undefined, 'test-secret', Date.now())!
    const incoming = new Request('http://0.0.0.0:3000/api/metrics', {
      method,
      headers: { origin, host: 'website.example', 'content-type': 'application/json', cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` },
      body: JSON.stringify(method === 'POST' ? { events: [event()] } : {}),
    })
    const response = await handlers[method](incoming)
    expect(response.status).toBe(202)
    expect(await response.json()).toEqual({ delivered: true })
    expect(handlers.fetcher).toHaveBeenCalledOnce()
    if (method === 'DELETE') expect(response.headers.get('set-cookie')).not.toContain(visitor.cookieValue)
  })
  it.each(['POST', 'DELETE'] as const)('rejects invalid proxy origin boundaries for %s before forwarding', async method => {
    const { fetcher } = setup()
    const handlers = createMetricsHandlers({ secret: 'test-secret', allowedOrigins: [origin, 'https://other.example', 'https://website.example/path', 'null'], bridge: {}, fetchImpl: fetcher })
    const cases: Record<string, string>[] = [
      { host: 'website.example' },
      { host: 'website.example', origin: 'null' },
      { host: 'website.example', origin: 'https://website.example/path' },
      { host: 'website.example', origin: 'https://evil.example' },
      { host: 'evil.example', origin: 'https://evil.example' },
      { host: 'website.example', origin: 'https://other.example' },
      { host: 'other.example', origin, 'x-forwarded-host': 'website.example', 'x-forwarded-proto': 'https', forwarded: 'host=website.example;proto=https' },
      { origin, 'x-forwarded-host': 'website.example', 'x-forwarded-proto': 'https' },
      { host: 'website.example:8443', origin },
      { host: 'website.example', origin: 'http://website.example' },
    ]
    for (const headers of cases) {
      const incoming = new Request('http://0.0.0.0:3000/api/metrics', {
        method, headers: { 'content-type': 'application/json', ...headers },
        body: JSON.stringify(method === 'POST' ? { events: [event()] } : {}),
      })
      expect((await handlers[method](incoming)).status, JSON.stringify(headers)).toBe(403)
    }
    const disabled = createMetricsHandlers({ allowedOrigins: [], bridge: {}, fetchImpl: fetcher })
    expect((await disabled[method](new Request('http://0.0.0.0:3000/api/metrics', {
      method, headers: { origin, host: 'website.example', 'content-type': 'application/json' }, body: '{}',
    }))).status).toBe(403)
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('test_cross_origin_and_server_fact_in_browser_batch_rejected', async () => {
    const { POST, fetcher } = setup()
    expect((await POST(request({ events: [event()] }, { origin: 'https://evil.example' }))).status).toBe(403)
    const missing = request({ events: [event()] }); missing.headers.delete('origin')
    expect((await POST(missing)).status).toBe(403)
    expect((await POST(request({ events: [{ ...event(), name: 'analysis_finished' }] }))).status).toBe(400)
    expect((await POST(request({ events: [{ ...event(), subjectId: crypto.randomUUID() }] }))).status).toBe(400)
    expect((await POST(request({ events: [{ ...event(), properties: { cost: 1 } }] }))).status).toBe(400)
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('sets trusted identity with hard expiry and rejects body/batch/rate overflow', async () => {
    const { POST, fetcher } = setup()
    const response = await POST(request({ events: [event()] }))
    expect(response.status).toBe(202)
    expect(response.headers.get('set-cookie')).toMatch(/HttpOnly/)
    expect(response.headers.get('set-cookie')).toMatch(/Secure/)
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({ source: 'website_client', events: [{ subjectKind: 'visitor' }] })
    expect((await POST(request({ events: Array.from({ length: 21 }, event) }))).status).toBe(400)
    expect((await POST(request('x'.repeat(32769)))).status).toBe(413)
  })
  it('does not renew an existing visitor and sets expiry from issuance on rotation', async () => {
    const time = Date.now()
    const visitor = resolveVisitor(undefined, 'test-secret', time)!
    const fetcher = vi.fn(async (_url: RequestInfo | URL, options?: RequestInit) => options?.method === 'DELETE' ? Response.json({deleted:0}) : Response.json({accepted:JSON.parse(String(options?.body)).events.length,duplicates:0}))
    const handlers = createMetricsHandlers({ secret: 'test-secret', now: () => time + 1000, allowedOrigins: [origin], bridge: { backendUrl: 'https://collector.example', bridgeKey: 'secret', environment: 'development', runtime: 'production' }, fetchImpl: fetcher })
    const existing = await handlers.POST(request({ events: [event()] }, { cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` }))
    expect(existing.headers.get('set-cookie')).toBeNull()
    const fresh = await handlers.POST(request({ events: [event()] }))
    expect(fresh.headers.get('set-cookie')).toContain(new Date(time + 1000 + VISITOR_LIFETIME_MS).toUTCString())
  })
  it('safely handles delivery failure and missing cookie secret without forwarding', async () => {
    const { POST, fetcher } = setup()
    fetcher.mockRejectedValue(new Error('secret raw failure'))
    const failed = await POST(request({ events: [event()] }))
    expect(failed.status).toBe(202)
    expect(await failed.json()).toEqual({ delivered: false })
    const disabled = createMetricsHandlers({ allowedOrigins: [origin], bridge: {}, fetchImpl: fetcher })
    fetcher.mockClear()
    expect(await (await disabled.POST(request({ events: [event()] }))).json()).toEqual({ delivered: false })
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('rejects foreign and oversized DELETE requests before delivery', async () => {
    const { DELETE, fetcher } = setup()
    expect((await DELETE(request({}, { origin: 'https://evil.example' }, 'DELETE'))).status).toBe(403)
    expect((await DELETE(request('x'.repeat(32769), {}, 'DELETE'))).status).toBe(413)
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('test_visitor_delete_uses_signed_cookie_only', async () => {
    const { DELETE, fetcher } = setup()
    fetcher.mockRejectedValue(new Error('outage'))
    const visitor = resolveVisitor(undefined, 'test-secret', Date.now())!
    const response = await DELETE(request({}, { cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` }, 'DELETE'))
    expect(response.status).toBe(202)
    expect(fetcher.mock.calls[0][0]).toBe(`https://collector.example/internal/metrics/visitors/${visitor.visitorId}`)
    expect(response.headers.get('set-cookie')).not.toContain(visitor.cookieValue)
    expect((await DELETE(request({ visitorId: crypto.randomUUID() }, {}, 'DELETE'))).status).toBe(400)
  })
})

it('preserves backend rate-limit delay and visitor cookie on an uncommitted batch', async () => {
  const { POST, fetcher } = setup()
  fetcher.mockImplementation(async () => new Response(null, { status: 429, headers: { 'Retry-After': '37' } }))
  const response = await POST(request({ events: [event()] }))
  expect(response.status).toBe(429)
  expect(response.headers.get('Retry-After')).toBe('37')
  expect(response.headers.get('set-cookie')).toContain(VISITOR_COOKIE)
  expect(await response.json()).toEqual({ delivered: false })
})

it('isolates a noisy signed visitor without spending the aggregate budget on rejected requests', async () => {
  const { POST, fetcher } = setup()
  const visitor = resolveVisitor(undefined, 'test-secret', Date.now())!
  const headers = { cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` }
  for (let i = 0; i < 30; i++) expect((await POST(request({ events: [event()] }, headers))).status).toBe(202)
  for (let i = 0; i < 650; i++) {
    const rejected = await POST(request({ events: [event()] }, headers))
    expect(rejected.status).toBe(429)
    expect(Number(rejected.headers.get('Retry-After'))).toBeGreaterThan(0)
  }
  expect((await POST(request({ events: [event()] }))).status).toBe(202)
  expect(fetcher).toHaveBeenCalledTimes(31)
})

it('admits 31 visitors with two pulses and two additional page/action batches each minute', async () => {
  const { POST, fetcher } = setup()
  const visitors = Array.from({ length: 31 }, () => resolveVisitor(undefined, 'test-secret', Date.now())!)
  for (const visitor of visitors) {
    const headers = { cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` }
    for (let i = 0; i < 4; i++) expect((await POST(request({ events: [event()] }, headers))).status).toBe(202)
  }
  expect(fetcher).toHaveBeenCalledTimes(124)
})

it('bounds aggregate admission, shares POST/DELETE visitor budget, and resets the window', async () => {
  let time = Date.parse('2026-10-25T00:00:30Z')
  const handlers = createMetricsHandlers({ secret: 'test-secret', allowedOrigins: [origin], now: () => time,
    rateLimits: { aggregate: 2, perVisitor: 1 }, bridge: {} })
  const visitor = resolveVisitor(undefined, 'test-secret', time)!
  const headers = { cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` }
  expect((await handlers.POST(request({ events: [event()] }, headers))).status).toBe(202)
  const limited = await handlers.DELETE(request({}, headers, 'DELETE'))
  expect(limited.status).toBe(429)
  expect(limited.headers.get('Retry-After')).toBe('30')
  expect((await handlers.POST(request({ events: [event()] }))).status).toBe(202)
  expect((await handlers.POST(request({ events: [event()] }))).status).toBe(429)
  time += 30000
  expect((await handlers.POST(request({ events: [event()] }, headers))).status).toBe(202)
})

it.each(['visitor', 'aggregate'] as const)('rotates identity when DELETE exhausts the %s budget', async budget => {
  let time = Date.parse('2026-10-25T00:00:30Z')
  const { fetcher } = setup()
  const handlers = createMetricsHandlers({ secret: 'test-secret', allowedOrigins: [origin], now: () => time,
    ...(budget === 'aggregate' ? { rateLimits: { aggregate: 30, perVisitor: 60 } } : {}),
    bridge: { backendUrl: 'https://collector.example', bridgeKey: 'secret', environment: 'development', runtime: 'production' }, fetchImpl: fetcher })
  const visitor = resolveVisitor(undefined, 'test-secret', time)!
  const headers = { cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` }
  for (let i = 0; i < 30; i++) expect((await handlers.POST(request({ events: [event()] }, headers))).status).toBe(202)
  const deleted = await handlers.DELETE(request({}, headers, 'DELETE'))
  expect(deleted.status).toBe(429)
  expect(deleted.headers.get('Retry-After')).toBe('30')
  const rotatedCookie = deleted.cookies.get(VISITOR_COOKIE)?.value
  expect(rotatedCookie).toBeTruthy()
  const rotated = resolveVisitor(rotatedCookie, 'test-secret', time)!
  expect(rotated.isNew).toBe(false)
  expect(rotated.visitorId).not.toBe(visitor.visitorId)
  expect(deleted.headers.get('set-cookie')).toMatch(/HttpOnly.*Secure|Secure.*HttpOnly/)
  expect(fetcher).toHaveBeenCalledTimes(30)
  time += 30000
  expect((await handlers.POST(request({ events: [event()] }, { cookie: `${VISITOR_COOKIE}=${rotatedCookie}` }))).status).toBe(202)
  expect(JSON.parse(String(fetcher.mock.calls[30][1]?.body)).events[0].subjectId).toBe(rotated.visitorId)
})

it.each([0, -1, 1.5, NaN, 100001])('rejects invalid configured limit %s', value => {
  expect(() => createMetricsHandlers({ allowedOrigins: [origin], bridge: {}, rateLimits: { aggregate: value, perVisitor: 30 } })).toThrow()
})

it('diagnoses missing cookie configuration without forwarding', async () => {
  const log = vi.spyOn(console, 'warn').mockImplementation(() => {})
  const fetcher = vi.fn()
  try {
    const handlers = createMetricsHandlers({ allowedOrigins: [origin], bridge: {}, fetchImpl: fetcher })
    expect(await (await handlers.POST(request({ events: [event()] }))).json()).toEqual({ delivered: false })
    expect(fetcher).not.toHaveBeenCalled()
    expect(log).toHaveBeenCalledWith('fitcheck_metrics_relay', { outcome: 'cookie_unconfigured' })
  } finally { log.mockRestore() }
})

it.each(['fitcheck_guest', '__Host-fitcheck_guest'])('forwards only the unambiguous guest proof for demo observations (%s)', async name => {
  const { POST, fetcher } = setup()
  const payload = { ...event(), name: 'analysis_requested', properties: { flow: 'demo', locale: 'ru', inputMode: 'text', requestId: crypto.randomUUID() } }
  expect((await POST(request({ events: [payload] }, { cookie: `${name}=guest-proof; fitcheck_session=private; unrelated=secret` }))).status).toBe(202)
  expect(new Headers(fetcher.mock.calls[0][1]?.headers).get('cookie')).toBe(`${name}=guest-proof`)
  await POST(request({ events: [payload] }, { cookie: `${name}=a; ${name}=b` }))
  expect(new Headers(fetcher.mock.calls[1][1]?.headers).get('cookie')).toBeNull()
  await POST(request({ events: [event()] }, { cookie: `${name}=guest-proof` }))
  expect(new Headers(fetcher.mock.calls[2][1]?.headers).get('cookie')).toBeNull()
})
