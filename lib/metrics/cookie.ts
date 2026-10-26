import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto'
import { uuidSchema } from './types'

export const VISITOR_COOKIE = 'fitcheck_visitor'
export const VISITOR_LIFETIME_MS = 180 * 24 * 60 * 60 * 1000
const domain = 'fitcheck:metrics:visitor:v1:'
const signature = (value: string, secret: string) => createHmac('sha256', secret).update(domain + value).digest('base64url')
export function resolveVisitor(cookieValue: string | undefined, secret: string | undefined, now: number) {
  if (!secret || !Number.isSafeInteger(now) || now < 0) return null
  if (cookieValue && cookieValue.length < 200) {
    const [version, visitorId, issued, mac, ...extra] = cookieValue.split('.')
    const issuedAt = Number(issued)
    if (version === '1' && uuidSchema.safeParse(visitorId).success && visitorId !== '00000000-0000-0000-0000-000000000000' && /^\d+$/.test(issued) && Number.isSafeInteger(issuedAt) && issuedAt >= 0 && issuedAt <= now && now < issuedAt + VISITOR_LIFETIME_MS && !extra.length && /^[A-Za-z0-9_-]{43}$/.test(mac ?? '')) {
      const expected = Buffer.from(signature(`${version}.${visitorId}.${issued}`, secret))
      const supplied = Buffer.from(mac)
      if (expected.length === supplied.length && timingSafeEqual(expected, supplied)) return { visitorId, cookieValue, isNew: false, expiresAt: issuedAt + VISITOR_LIFETIME_MS }
    }
  }
  const visitorId = randomUUID()
  const unsigned = `1.${visitorId}.${now}`
  return { visitorId, cookieValue: `${unsigned}.${signature(unsigned, secret)}`, isNew: true, expiresAt: now + VISITOR_LIFETIME_MS }
}
