import { describe, expect, it, vi } from 'vitest'
import { sendMetrics } from './bridge'
const config = { backendUrl: 'https://collector.example', bridgeKey: 'secret', environment: 'development' as const, runtime: 'production' }
const batch = { source: 'website_client' as const, events: [] }
describe('bridge', () => {
  it('test_bridge_failure_returns_nonblocking_safe_result', async () => {
    expect(await sendMetrics(batch, config, vi.fn().mockRejectedValue(new Error('private error')))).toBe(false)
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
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
    expect(await sendMetrics(batch, { ...config, backendUrl: 'http://127.0.0.1:8000', runtime: 'development', allowLocalHttp: true }, vi.fn().mockResolvedValue(new Response()))).toBe(true)
  })
  it('times out even when injected transport ignores abort', async () => {
    vi.useFakeTimers()
    const result = sendMetrics(batch, config, vi.fn(() => new Promise<Response>(() => {})))
    await vi.advanceTimersByTimeAsync(1500)
    expect(await result).toBe(false)
    vi.useRealTimers()
  })
})
