import { describe, expect, it, vi } from 'vitest'
import { createMetricsHandlers } from './handler'
import { resolveVisitor, VISITOR_COOKIE, VISITOR_LIFETIME_MS } from '@/lib/metrics/cookie'
const origin = 'https://website.example'
const event = () => ({ eventId: crypto.randomUUID(), name: 'page_viewed', schemaVersion: 1, occurredAt: new Date().toISOString(), sessionId: crypto.randomUUID(), properties: {} })
const request = (body: unknown, headers: Record<string, string> = {}, method = 'POST') => new Request(`${origin}/api/metrics`, { method, headers: { origin, 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) })
const setup = () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
  const handlers = createMetricsHandlers({ secret: 'test-secret', allowedOrigins: [origin], bridge: { backendUrl: 'https://collector.example', bridgeKey: 'secret', environment: 'development', runtime: 'production' }, fetchImpl: fetcher })
  return { ...handlers, fetcher }
}
describe('browser metrics boundary', () => {
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
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({ source: 'website_client', events: [{ subjectKind: 'visitor' }] })
    expect((await POST(request({ events: Array.from({ length: 21 }, event) }))).status).toBe(400)
    expect((await POST(request('x'.repeat(32769)))).status).toBe(413)
    for (let i = 0; i < 57; i++) await POST(request({ events: [event()] }))
    expect((await POST(request({ events: [event()] }))).status).toBe(429)
  })
  it('does not renew an existing visitor and sets expiry from issuance on rotation', async () => {
    const time = Date.now()
    const visitor = resolveVisitor(undefined, 'test-secret', time)!
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
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
