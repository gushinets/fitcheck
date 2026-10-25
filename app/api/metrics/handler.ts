import { NextResponse } from 'next/server'
import { z } from 'zod'
import { deleteVisitorMetrics, sendMetricsWithReceipt } from '@/lib/metrics/bridge'
import type { BridgeConfig } from '@/lib/metrics/bridge'
import { resolveVisitor, VISITOR_COOKIE } from '@/lib/metrics/cookie'
import { MAX_BATCH_BYTES, MAX_BATCH_EVENTS, validateClientEvent } from '@/lib/metrics/types'

interface HandlerConfig {
  secret?: string
  allowedOrigins: string[]
  bridge: BridgeConfig
  fetchImpl?: typeof fetch
  now?: () => number
  rateLimits?: { aggregate: number; perVisitor: number }
}
const envelope = z.strictObject({ events: z.array(z.unknown()).min(1).max(MAX_BATCH_EVENTS) })
const empty = z.strictObject({})
class BodyTooLarge extends Error {}
async function readBody(request: Request): Promise<unknown> {
  const length = request.headers.get('content-length')
  if (length && (!/^\d+$/.test(length) || Number(length) > MAX_BATCH_BYTES)) throw new BodyTooLarge()
  if (!request.body) return {}
  const reader = request.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > MAX_BATCH_BYTES) { await reader.cancel(); throw new BodyTooLarge() }
      chunks.push(value)
    }
  } finally { reader.releaseLock() }
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length }
  return size ? JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) : {}
}
const response = (value: object, status: number) => NextResponse.json(value, { status, headers: { 'Cache-Control': 'no-store' } })
export function createMetricsHandlers(config: HandlerConfig) {
  const now = config.now ?? Date.now
  const limits = z.object({ aggregate: z.number().int().min(1).max(100000), perVisitor: z.number().int().min(1).max(100000) })
    .parse(config.rateLimits ?? { aggregate: 600, perVisitor: 30 })
  let window = Math.floor(now() / 60000), count = 0
  // At most aggregate entries in a minute. Keys are verified visitor IDs, never raw IPs.
  const visitors = new Map<string, number>()
  function rateLimit(visitor: NonNullable<ReturnType<typeof resolveVisitor>>) {
    const time = now(), current = Math.floor(time / 60000)
    if (current !== window) { window = current; count = 0; visitors.clear() }
    const attempts = visitors.get(visitor.visitorId) ?? 0
    if (attempts >= limits.perVisitor || count >= limits.aggregate) {
      const reply = response({ error: 'rate_limited' }, 429)
      reply.headers.set('Retry-After', String(Math.max(1, Math.ceil(((window + 1) * 60000 - time) / 1000))))
      if (visitor.isNew) cookie(reply, visitor)
      return reply
    }
    visitors.set(visitor.visitorId, attempts + 1)
    count++
  }
  function guard(request: Request) {
    const origin = request.headers.get('origin')
    let sameHost = false
    if (origin && config.allowedOrigins.includes(origin)) {
      try {
        const parsed = new URL(origin)
        // TLS termination can leave request.url on an internal origin. Use the
        // public Host only with an exact configured Origin; never forwarded headers.
        sameHost = ['http:', 'https:'].includes(parsed.protocol) && parsed.origin === origin &&
          (origin === new URL(request.url).origin || request.headers.get('host') === parsed.host)
      } catch { /* Malformed origins fail closed. */ }
    }
    if (!sameHost) return response({ error: 'origin_not_allowed' }, 403)
    if (request.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') return response({ error: 'invalid_request' }, 400)
  }
  function incomingCookie(request: Request) {
    const values = (request.headers.get('cookie') ?? '').split(';').map(value => value.trim()).filter(value => value.startsWith(`${VISITOR_COOKIE}=`))
    return values.length === 1 ? values[0].slice(VISITOR_COOKIE.length + 1) : undefined
  }
  function cookie(reply: NextResponse, visitor: NonNullable<ReturnType<typeof resolveVisitor>>) {
    reply.cookies.set(VISITOR_COOKIE, visitor.cookieValue, { httpOnly: true, secure: config.bridge.runtime === 'production', sameSite: 'lax', path: '/', expires: new Date(visitor.expiresAt) })
  }
  async function body(request: Request) {
    try { return { value: await readBody(request) } }
    catch (error) { return { error: response({ error: error instanceof BodyTooLarge ? 'body_too_large' : 'invalid_request' }, error instanceof BodyTooLarge ? 413 : 400) } }
  }
  return {
    async POST(request: Request) {
      const rejected = guard(request); if (rejected) return rejected
      const parsed = await body(request); if (parsed.error) return parsed.error
      const batch = envelope.safeParse(parsed.value)
      if (!batch.success) return response({ error: 'invalid_request' }, 400)
      const events = batch.data.events.map(validateClientEvent)
      if (events.some(event => event === null)) return response({ error: 'invalid_request' }, 400)
      const visitor = resolveVisitor(incomingCookie(request), config.secret, now())
      if (!visitor) {
        try { console.warn('fitcheck_metrics_relay', { outcome: 'cookie_unconfigured' }) } catch { /* Best effort only. */ }
        return response({ delivered: false }, 202)
      }
      const limited = rateLimit(visitor); if (limited) return limited
      const guestCookies = (request.headers.get('cookie') ?? '').split(';').map(value => value.trim())
        .filter(value => /^(?:__Host-)?fitcheck_guest=/.test(value))
      const guestCookie = events.some(event => event?.properties && 'flow' in event.properties && event.properties.flow === 'demo') &&
        guestCookies.length === 1 && /^(?:__Host-)?fitcheck_guest=[A-Za-z0-9_-]+$/.test(guestCookies[0]) ? guestCookies[0] : undefined
      const result = await sendMetricsWithReceipt({ source: 'website_client', events: events.map(event => ({ ...event!, subjectId: visitor.visitorId, subjectKind: 'visitor' })) }, config.bridge, config.fetchImpl, guestCookie)
      const reply = response({ delivered: result.delivered }, result.retryAfterMs === undefined ? 202 : 429)
      if (result.retryAfterMs !== undefined) reply.headers.set('Retry-After', String(Math.ceil(result.retryAfterMs / 1000)))
      if (visitor.isNew) cookie(reply, visitor)
      return reply
    },
    async DELETE(request: Request) {
      const rejected = guard(request); if (rejected) return rejected
      const parsed = await body(request); if (parsed.error) return parsed.error
      if (!empty.safeParse(parsed.value).success) return response({ error: 'invalid_request' }, 400)
      const previous = resolveVisitor(incomingCookie(request), config.secret, now())
      if (previous) { const limited = rateLimit(previous); if (limited) return limited }
      const next = resolveVisitor(undefined, config.secret, now())
      // Remote deletion delivery cannot prevent issuing the rotated cookie.
      const delivered = !next ? false : previous && !previous.isNew ? await deleteVisitorMetrics(previous.visitorId, config.bridge, config.fetchImpl) : true
      const result = response({ delivered }, 202)
      if (next) cookie(result, next)
      return result
    },
  }
}
