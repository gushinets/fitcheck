// @vitest-environment node
import { afterEach, expect, it, vi } from 'vitest'
import { beginWebsiteOperation, deliveryCounters } from './operations'
import { resolveVisitor, VISITOR_COOKIE } from './cookie'
import { NextRequest } from 'next/server'
import { proxy } from '@/proxy'
afterEach(()=>vi.unstubAllEnvs())
function config() {
  vi.stubEnv('METRICS_COOKIE_SECRET','test-secret')
  vi.stubEnv('METRICS_ENVIRONMENT','test')
  vi.stubEnv('METRICS_BACKEND_URL','https://metrics.example')
  vi.stubEnv('METRICS_BRIDGE_KEY','private-key')
}
it('test_server_success_requires_grounding_validation', async () => {
  config()
  const pending: (()=>Promise<void>)[] = [], fetcher = vi.fn().mockResolvedValue(new Response('{}'))
  const visitor = resolveVisitor(undefined,'test-secret',Date.now())!
  const op = beginWebsiteOperation(new Request('https://app.test/api/analyze',{headers:{cookie:`${VISITOR_COOKIE}=${visitor.cookieValue}`}}),'analysis',cb=>pending.push(cb),fetcher)!
  // Failed domain validation cannot be counted as a server success.
  const response = op.complete(Response.json({error:'analysis_invalid_output'},{status:502}))
  expect(response.headers.get('set-cookie')).toBeNull()
  expect(response.headers.get('X-FitCheck-Operation-Id')).toBeNull()
  expect(fetcher).not.toHaveBeenCalled()
  await pending[0]()
  expect(JSON.parse(fetcher.mock.calls[0][1].body).events[0].properties.outcome).toBe('failed')
})
it('document proxy allocates once, scopes to root documents and preserves cookie hard expiry', () => {
  config()
  const first = proxy(new NextRequest('https://app.test/',{headers:{accept:'text/html'}}))
  const value = first.cookies.get(VISITOR_COOKIE)!.value
  const next = proxy(new NextRequest('https://app.test/',{headers:{accept:'text/html',cookie:`${VISITOR_COOKIE}=${value}`}}))
  expect(next.cookies.get(VISITOR_COOKIE)).toBeUndefined()
  expect(proxy(new NextRequest('https://app.test/api/analyze',{headers:{accept:'text/html'}})).cookies.get(VISITOR_COOKIE)).toBeUndefined()
  expect(proxy(new NextRequest('https://app.test/',{headers:{accept:'application/json'}})).cookies.get(VISITOR_COOKIE)).toBeUndefined()
})
it('bounded delivery queue drops safely without delaying foreground work', async () => {
  config()
  const callbacks: (()=>Promise<void>)[] = []
  const before = deliveryCounters.dropped
  const op = beginWebsiteOperation(new Request('https://app.test/api/analyze'),'analysis',cb=>callbacks.push(cb),vi.fn().mockResolvedValue(new Response('{}')))!
  for(let i=0;i<110;i++) await op.sink.start({callId:String(i)} as never)
  expect(deliveryCounters.dropped).toBeGreaterThan(before)
  op.complete(Response.json({score:42}))
  await callbacks[0]()
})
it('collector outage preserves validated DTO and records only safe delivery counters', async()=>{
  config()
  const callbacks:(()=>Promise<void>)[]=[]
  const before=deliveryCounters.failed
  const operation=beginWebsiteOperation(new Request('https://app.test/api/analyze'),'analysis',cb=>callbacks.push(cb),vi.fn().mockResolvedValue(new Response('{}',{status:503})))!
  const dto={score:42,label:'private report'}
  const response=operation.complete(Response.json(dto))
  expect(await response.json()).toEqual(dto)
  expect(response.status).toBe(200)
  await callbacks[0]()
  expect(deliveryCounters.failed).toBe(before+1)
})
