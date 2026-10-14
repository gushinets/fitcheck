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
async function deliver(path: string, method: string, body: string | undefined, config: BridgeConfig, fetchImpl: typeof fetch): Promise<boolean> {
  const url = destination(config)
  if (!url || body !== undefined && new TextEncoder().encode(body).length > MAX_BATCH_BYTES) return false
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    const timeout = new Promise<boolean>(resolve => {
      timer = setTimeout(() => { controller.abort(); resolve(false) }, 1500)
    })
    const delivery = Promise.resolve().then(() => fetchImpl(new URL(path, url).href, {
      method, redirect: 'error', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'X-FitCheck-Metrics-Key': config.bridgeKey! },
      body,
    })).then(response => response.ok, () => false)
    return await Promise.race([delivery, timeout])
  } catch { return false }
  finally { if (timer !== undefined) clearTimeout(timer) }
}
export async function sendMetrics(batch: WebsiteBatch, config: BridgeConfig, fetchImpl: typeof fetch = fetch): Promise<boolean> {
  try { return await deliver('/internal/metrics/events', 'POST', JSON.stringify(batch), config, fetchImpl) }
  catch { return false }
}
export async function deleteVisitorMetrics(visitorId: string, config: BridgeConfig, fetchImpl: typeof fetch = fetch): Promise<boolean> {
  if (!uuidSchema.safeParse(visitorId).success) return false
  return deliver(`/internal/metrics/visitors/${visitorId}`, 'DELETE', undefined, config, fetchImpl)
}
