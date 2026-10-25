import { createMetricsHandlers } from './handler'
import type { MetricsEnvironment } from '@/lib/metrics/types'

export const runtime = 'nodejs'
let handlers: ReturnType<typeof createMetricsHandlers> | undefined
function getHandlers() {
  handlers ??= createMetricsHandlers({
    secret: process.env.METRICS_COOKIE_SECRET,
    allowedOrigins: (process.env.ALLOWED_ORIGINS ?? 'http://localhost:3000').split(',').map(origin => origin.trim()).filter(Boolean),
    rateLimits: {
      aggregate: Number(process.env.METRICS_RATE_LIMIT_PER_MINUTE ?? 600),
      perVisitor: Number(process.env.METRICS_VISITOR_RATE_LIMIT_PER_MINUTE ?? 30),
    },
    bridge: {
      backendUrl: process.env.METRICS_BACKEND_URL,
      bridgeKey: process.env.METRICS_BRIDGE_KEY,
      environment: process.env.METRICS_ENVIRONMENT as MetricsEnvironment | undefined,
      runtime: process.env.NODE_ENV,
      allowLocalHttp: process.env.METRICS_ALLOW_LOCAL_HTTP === 'true',
    },
  })
  return handlers
}
export async function POST(request: Request) { return getHandlers().POST(request) }
export async function DELETE(request: Request) { return getHandlers().DELETE(request) }
