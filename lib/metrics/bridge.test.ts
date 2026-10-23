import { describe, expect, it, vi } from 'vitest'
import { sendMetrics, bridgeReadiness } from './bridge'
const config = { backendUrl: 'https://collector.example', bridgeKey: 'secret', environment: 'development' as const, runtime: 'production' }
const batch = { source: 'website_client' as const, events: [] }
describe('bridge', () => {
  it('test_bridge_failure_returns_nonblocking_safe_result', async () => {
    expect(await sendMetrics(batch, config, vi.fn().mockRejectedValue(new Error('private error')))).toBe(false)
    const fetcher = vi.fn().mockResolvedValue(Response.json({ accepted: 0, duplicates: 0 }))
    expect(await sendMetrics(batch, config, fetcher)).toBe(true)
    expect(fetcher.mock.calls[0][0]).toBe('https://collector.example/internal/metrics/events')
    expect(fetcher.mock.calls[0][1]).toMatchObject({ redirect: 'error', headers: { 'X-FitCheck-Metrics-Key': 'secret' } })
    expect(fetcher.mock.calls[0][1].headers.Origin).toBeUndefined()
  })
  it('rejects unsafe destinations and only permits explicit local loopback', async () => {
    for (const backendUrl of ['http://collector.example', 'https://u:p@collector.example', 'https://collector.example/?key=secret', 'https://collector.example/path', 'http://127.0.0.1:8000']) {
      const fetcher = vi.fn()
      expect(await sendMetrics(batch, { ...config, backendUrl }, fetcher)).toBe(false)
      expect(fetcher).not.toHaveBeenCalled()
    }
    expect(await sendMetrics(batch, { ...config, backendUrl: 'http://127.0.0.1:8000', runtime: 'development', allowLocalHttp: true }, vi.fn().mockResolvedValue(Response.json({accepted:0,duplicates:0})))).toBe(true)
  })
  it('times out even when injected transport ignores abort', async () => {
    vi.useFakeTimers()
    const result = sendMetrics(batch, config, vi.fn(() => new Promise<Response>(() => {})))
    await vi.advanceTimersByTimeAsync(1500)
    expect(await result).toBe(false)
    vi.useRealTimers()
  })
})

it('diagnoses invalid configuration without exposing secrets', async () => {
  const log = vi.spyOn(console, 'warn').mockImplementation(() => {})
  try {
    expect(bridgeReadiness({ ...config, bridgeKey: undefined })).toEqual({ configured: false, reason: 'missing_configuration' })
    expect(bridgeReadiness({ ...config, backendUrl: 'http://unsafe.example' })).toEqual({ configured: false, reason: 'invalid_destination' })
    expect(await sendMetrics(batch, { ...config, bridgeKey: undefined })).toBe(false)
    expect(log).toHaveBeenCalledWith('fitcheck_metrics_bridge', { outcome: 'missing_configuration', operation: 'events' })
    expect(JSON.stringify(log.mock.calls)).not.toContain('secret')
  } finally { log.mockRestore() }
})
it.each([401, 403, 429, 503])('diagnoses collector rejection %s', async status => {
  const log = vi.spyOn(console, 'warn').mockImplementation(() => {})
  try {
    expect(await sendMetrics(batch, config, vi.fn().mockResolvedValue(new Response('private', { status })))).toBe(false)
    expect(log).toHaveBeenCalledWith('fitcheck_metrics_bridge', { outcome: 'collector_rejected', operation: 'events', status })
    expect(JSON.stringify(log.mock.calls)).not.toContain('private')
  } finally { log.mockRestore() }
})
it('does not acknowledge an asynchronous collector response as committed delivery', async () => {
  expect(await sendMetrics(batch, config, vi.fn().mockResolvedValue(Response.json({ delivered: false }, { status: 202 })))).toBe(false)
})
it('emits one timeout diagnostic even if transport completes later', async () => {
  vi.useFakeTimers()
  const log = vi.spyOn(console, 'warn').mockImplementation(() => {})
  let finish!: (response: Response) => void
  try {
    const delivery = sendMetrics(batch, config, () => new Promise(resolve => { finish = resolve }))
    await vi.advanceTimersByTimeAsync(1500)
    expect(await delivery).toBe(false)
    finish(new Response())
    await Promise.resolve()
    expect(log.mock.calls).toEqual([['fitcheck_metrics_bridge', { outcome: 'timeout', operation: 'events' }]])
  } finally { log.mockRestore(); vi.useRealTimers() }
})

it('keeps bridge failures nonblocking when diagnostic output throws', async () => {
  const log = vi.spyOn(console, 'warn').mockImplementation(() => { throw new Error('logging failed') })
  try { expect(await sendMetrics(batch, { ...config, bridgeKey: undefined })).toBe(false) }
  finally { log.mockRestore() }
})

it.each([() => new Response('<html>proxy</html>'), () => new Response(null, { status: 204 }), () => Response.json({delivered:false}), () => Response.json({accepted:1,duplicates:0}), () => Response.json({accepted:-1,duplicates:1})])('requires an exact collector acknowledgement', async response => {
  expect(await sendMetrics(batch, config, vi.fn().mockResolvedValue(response()))).toBe(false)
})
it('accepts a duplicate acknowledgement for the complete batch', async () => {
  expect(await sendMetrics({ ...batch, events: [{} as never] }, config, vi.fn().mockResolvedValue(Response.json({accepted:0,duplicates:1})))).toBe(true)
})
