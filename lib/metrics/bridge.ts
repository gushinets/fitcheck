// Server transport only: callers supply server configuration, never browser destinations.
import type { MetricsEnvironment, WebsiteBatch } from './types'
import { MAX_BATCH_BYTES, uuidSchema } from './types'
export interface BridgeConfig {
  backendUrl?: string
  bridgeKey?: string
  environment?: MetricsEnvironment
  runtime?: string
  allowLocalHttp?: boolean
}
function destination(config: BridgeConfig): URL | null {
  try {
    if (!config.backendUrl || !config.bridgeKey || !['development', 'production', 'test'].includes(config.environment ?? '')) return null
    const url = new URL(config.backendUrl)
    const local = ['development', 'test'].includes(config.runtime ?? '') && config.allowLocalHttp === true && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/' || (url.protocol !== 'https:' && !(url.protocol === 'http:' && local))) return null
    return url
  } catch { return null }
}
export function bridgeReadiness(config: BridgeConfig): { configured: boolean; reason: 'ready' | 'missing_configuration' | 'invalid_destination' } {
  if (!config.backendUrl || !config.bridgeKey || !config.environment) return { configured: false, reason: 'missing_configuration' }
  return destination(config) ? { configured: true, reason: 'ready' } : { configured: false, reason: 'invalid_destination' }
}
type Outcome = 'delivered' | 'missing_configuration' | 'invalid_destination' | 'body_too_large' | 'collector_rejected' | 'unconfirmed' | 'timeout' | 'network_error'
function diagnose(operation: string, outcome: Outcome, status?: number) {
  // Fixed fields only: never include URLs, keys, payloads or exception messages.
  try {
    const entry = { outcome, operation, ...(status === undefined ? {} : { status }) }
    if (outcome === 'delivered') console.info('fitcheck_metrics_bridge', entry)
    else console.warn('fitcheck_metrics_bridge', entry)
  } catch { /* Diagnostics cannot block product operations. */ }
}
async function deliver(path: string, method: string, body: string | undefined, config: BridgeConfig, fetchImpl: typeof fetch, expectedCount?: number, guestCookie?: string): Promise<boolean> {
  const operation = method === 'DELETE' ? 'delete' : path.endsWith('/attempts') ? 'attempts' : 'events'
  const readiness = bridgeReadiness(config)
  if (!readiness.configured) { diagnose(operation, readiness.reason as 'missing_configuration' | 'invalid_destination'); return false }
  const url = destination(config)!
  if (body !== undefined && new TextEncoder().encode(body).length > MAX_BATCH_BYTES) { diagnose(operation, 'body_too_large'); return false }
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  type Result = { outcome: Outcome; status?: number }
  try {
    const timeout = new Promise<Result>(resolve => {
      timer = setTimeout(() => { resolve({ outcome: 'timeout' }); controller.abort() }, 1500)
    })
    const delivery: Promise<Result> = Promise.resolve().then(() => fetchImpl(new URL(path, url).href, {
      method, redirect: 'error', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-FitCheck-Metrics-Key': config.bridgeKey!, ...(guestCookie ? { Cookie: guestCookie } : {}) },
      body,
    })).then(async (response): Promise<Result> => {
      if (!response.ok) return { outcome: 'collector_rejected', status: response.status }
      if (response.status !== 200) return { outcome: 'unconfirmed', status: response.status }
      try {
        const receipt = await response.json()
        const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
        const confirmed = receipt !== null && typeof receipt === 'object' && (method === 'DELETE'
          ? count(receipt.deleted)
          : count(receipt.accepted) && count(receipt.duplicates) && receipt.accepted + receipt.duplicates === expectedCount)
        return { outcome: confirmed ? 'delivered' : 'unconfirmed', status: response.status }
      } catch { return { outcome: 'unconfirmed', status: response.status } }
    }, () => ({ outcome: 'network_error' }))
    const result = await Promise.race([delivery, timeout])
    diagnose(operation, result.outcome, result.status)
    return result.outcome === 'delivered'
  } catch { diagnose(operation, 'network_error'); return false }
  finally { if (timer !== undefined) clearTimeout(timer) }
}
export async function sendMetrics(batch: WebsiteBatch, config: BridgeConfig, fetchImpl: typeof fetch = fetch, guestCookie?: string): Promise<boolean> {
  try { return await deliver('/internal/metrics/events', 'POST', JSON.stringify(batch), config, fetchImpl, batch.events.length, guestCookie) }
  catch { return false }
}
export async function deleteVisitorMetrics(visitorId: string, config: BridgeConfig, fetchImpl: typeof fetch = fetch): Promise<boolean> {
  if (!uuidSchema.safeParse(visitorId).success) return false
  return deliver(`/internal/metrics/visitors/${visitorId}`, 'DELETE', undefined, config, fetchImpl)
}

export async function sendAttempt(attempt: import('./provider').ProviderAttempt, config: BridgeConfig, fetchImpl: typeof fetch = fetch): Promise<boolean> {
  try {return await deliver('/internal/metrics/attempts','POST',JSON.stringify({source:'website_server',attempts:[attempt]}),config,fetchImpl,1)} catch {return false}
}
