import { afterEach, expect, it, vi } from 'vitest'
import { createMetricsClient, sendBrowserMetrics } from './client'
import { createMetricsHandlers } from '@/app/api/metrics/handler'
import { resolveVisitor, VISITOR_COOKIE } from './cookie'
import type { ClientEvent } from './types'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('delivers 31 continuously active visitors through two relays, including real pulses and page/action traffic', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-25T00:00:00Z'))
  const origin = 'https://website.example'
  const journal = new Map<string, ClientEvent>()
  let requests = 0
  const relays = Array.from({ length: 2 }, () => createMetricsHandlers({
    secret: 'capacity-secret', allowedOrigins: [origin], now: Date.now,
    bridge: { backendUrl: 'https://collector.example', bridgeKey: 'bridge-secret', environment: 'test' },
    // Committed collector boundary; real PostgreSQL admission/deduplication is
    // independently exercised by test_metrics_http.py and test_limits.py.
    fetchImpl: async (_url, options) => {
      requests++
      const events = JSON.parse(String(options?.body)).events as ClientEvent[]
      let accepted = 0
      for (const event of events) if (!journal.has(event.eventId)) { journal.set(event.eventId, event); accepted++ }
      return Response.json({ accepted, duplicates: events.length - accepted })
    },
  }))
  const clients = Array.from({ length: 31 }, (_, index) => {
    const visitor = resolveVisitor(undefined, 'capacity-secret', Date.now())!
    return createMetricsClient({ send: async events => {
      const reply = await relays[index % 2].POST(new Request(`${origin}/api/metrics`, {
        method: 'POST', headers: { origin, 'content-type': 'application/json', cookie: `${VISITOR_COOKIE}=${visitor.cookieValue}` },
        body: JSON.stringify({ events }),
      }))
      expect(reply.status).toBe(202)
      return (await reply.json()).delivered === true
    } })
  })
  try {
    for (const client of clients) client.track('page_viewed', {})
    await Promise.all(clients.map(client => client.flush()))
    // Keep every visitor active without causing extra scheduled HTTP requests.
    for (let second = 1; second <= 60; second++) {
      await vi.advanceTimersByTimeAsync(1000)
      document.dispatchEvent(new Event('pointerdown'))
      await Promise.all(clients.map(client => client.flush()))
    }
    for (const client of clients) client.track('history_viewed', {})
    await Promise.all(clients.map(client => client.flush()))
    expect(requests).toBe(124)
    expect([...journal.values()].filter(event => event.name === 'visible_activity')).toHaveLength(62)
    expect([...journal.values()].filter(event => event.name === 'page_viewed')).toHaveLength(31)
    for (const client of clients) expect(client.stats()).toMatchObject({ failed: 0, dropped: 0, queued: 0 })
  } finally { clients.forEach(client => client.dispose()) }
  expect(vi.getTimerCount()).toBe(0)
})

it('retains event IDs through a real browser transport and relay backend 429', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-25T00:00:00Z'))
  const seen: ClientEvent[][] = []
  const origin = 'https://website.example'
  const handlers = createMetricsHandlers({ secret: 'retry-secret', allowedOrigins: [origin],
    bridge: { backendUrl: 'https://collector.example', bridgeKey: 'key', environment: 'test' },
    fetchImpl: async (_url, options) => {
      const events = JSON.parse(String(options?.body)).events
      seen.push(events)
      return seen.length === 1 ? new Response(null, { status: 429, headers: { 'Retry-After': '5' } })
        : Response.json({ accepted: 0, duplicates: events.length })
    },
  })
  let cookie = ''
  vi.stubGlobal('fetch', async (_url: string, options: RequestInit) => {
    const reply = await handlers.POST(new Request(`${origin}/api/metrics`, {
      ...options, headers: { origin, 'content-type': 'application/json', cookie },
    }))
    cookie = reply.headers.get('set-cookie')?.split(';')[0] ?? cookie
    return reply
  })
  const client = createMetricsClient({ send: sendBrowserMetrics })
  try {
    client.track('page_viewed', {})
    const flushed = client.flush()
    await vi.advanceTimersByTimeAsync(4999)
    expect(seen).toHaveLength(1)
    expect(client.stats().delivered).toBe(0)
    await vi.advanceTimersByTimeAsync(1)
    await flushed
    expect(seen).toHaveLength(2)
    expect(seen[1]).toEqual(seen[0])
    expect(client.stats()).toMatchObject({ delivered: 2, failed: 0, queued: 0 })
  } finally { client.dispose() }
})
