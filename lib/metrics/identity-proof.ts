// Server-only attestation for the existing backend auth relay.
import { createHmac, randomUUID } from 'node:crypto'
import { resolveVisitor, VISITOR_COOKIE } from './cookie'

const paths = new Set(['/v1/auth/register', '/v1/auth/login', '/v1/guest-claims'])
export function visitorProof(request: Request, path: string, config: {
  cookieSecret?: string; bridgeKey?: string; environment?: string
}, now = Date.now()): string | undefined {
  try {
    if (request.method !== 'POST' || !paths.has(path) || !config.bridgeKey ||
      !['test', 'development', 'production'].includes(config.environment ?? '')) return
    const cookies = (request.headers.get('cookie') ?? '').split(';').map(v => v.trim())
      .filter(v => v.startsWith(`${VISITOR_COOKIE}=`))
    if (cookies.length !== 1) return
    const value = cookies[0].slice(VISITOR_COOKIE.length + 1)
    const visitor = resolveVisitor(value, config.cookieSecret, now)
    if (!visitor || visitor.isNew) return
    const payload = Buffer.from(JSON.stringify({ v: 1, environment: config.environment,
      visitorId: visitor.visitorId, cookieIssuedAt: Number(value.split('.')[2]),
      issuedAt: now, expiresAt: now + 120000, requestId: randomUUID(), method: 'POST', path,
    })).toString('base64url')
    const mac = createHmac('sha256', config.bridgeKey).update('fitcheck:metrics:identity:v1:' + payload).digest('base64url')
    return `${payload}.${mac}`
  } catch { /* Missing analytics context never blocks authentication. */ }
}
