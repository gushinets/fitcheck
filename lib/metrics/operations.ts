import { randomUUID } from 'node:crypto'
import { NextResponse } from 'next/server'
import { sendMetrics, sendAttempt } from './bridge'
import type { BridgeConfig } from './bridge'
import { resolveVisitor, VISITOR_COOKIE } from './cookie'
import type { MetricsEnvironment, WebsiteBatch } from './types'
import { createProviderAttemptSink } from './provider'

export type OperationName = 'analysis' | 'suggestions' | 'extraction'
export interface OperationContext {
  operationId: string
  visitorId: string
  environment: MetricsEnvironment
  name: OperationName
  startedAt: number
  now: () => number
}
export function createWebsiteOperation(options: {visitorId: string; environment: MetricsEnvironment; name: OperationName; now?: () => number}): OperationContext {
  const now = options.now ?? Date.now
  return {...options, now, startedAt: now(), operationId: randomUUID()}
}
export const deliveryCounters = { dropped: 0, failed: 0, delivered: 0 }
let pendingCount = 0
export function metricsConfiguration(): BridgeConfig {
  return {backendUrl:process.env.METRICS_BACKEND_URL,bridgeKey:process.env.METRICS_BRIDGE_KEY,
    environment:process.env.METRICS_ENVIRONMENT as MetricsEnvironment | undefined,runtime:process.env.NODE_ENV,
    allowLocalHttp:process.env.METRICS_ALLOW_LOCAL_HTTP === 'true'}
}
export function telemetryIdentityEnabled() {
  return !!process.env.METRICS_COOKIE_SECRET && ['development','production','test'].includes(process.env.METRICS_ENVIRONMENT ?? '')
}
export function requestVisitor(request: Request) {
  const values = (request.headers.get('cookie') ?? '').split(';').map(v=>v.trim()).filter(v=>v.startsWith(`${VISITOR_COOKIE}=`))
  return resolveVisitor(values.length === 1 ? values[0].slice(VISITOR_COOKIE.length+1) : undefined, process.env.METRICS_COOKIE_SECRET, Date.now())
}
export function setVisitorCookie(response: NextResponse, visitor: NonNullable<ReturnType<typeof resolveVisitor>>) {
  response.cookies.set(VISITOR_COOKIE,visitor.cookieValue,{httpOnly:true,secure:process.env.NODE_ENV === 'production',sameSite:'lax',path:'/',expires:new Date(visitor.expiresAt)})
}
// Delivery is best effort: bounded volatile memory, no persisted receipt or complete coverage claim.
export function beginWebsiteOperation(request: Request, name: OperationName, schedule: (callback:()=>Promise<void>)=>void, fetchImpl: typeof fetch = fetch) {
  if (!telemetryIdentityEnabled()) return null
  const visitor = requestVisitor(request)
  if (!visitor) return null
  const bridge = metricsConfiguration()
  const context = createWebsiteOperation({visitorId:visitor.visitorId,environment:bridge.environment!,name})
  const jobs: (()=>Promise<boolean>)[] = []
  let closed = false
  function enqueue(job:()=>Promise<boolean>) {
    if (closed || pendingCount >= 100) {deliveryCounters.dropped++; return}
    pendingCount++; jobs.push(job)
  }
  try {
    schedule(async()=>{
      closed = true
      // Parallel bounded deliveries keep collector timeouts outside the product deadline.
      await Promise.all(jobs.splice(0).map(async job=>{
        try { if(await job()) deliveryCounters.delivered++; else deliveryCounters.failed++ }
        catch {deliveryCounters.failed++}
        finally {pendingCount--}
      }))
    })
  } catch {closed=true; deliveryCounters.dropped++}
  const sink = createProviderAttemptSink(context,call=>{enqueue(()=>sendAttempt(call,bridge,fetchImpl)); return Promise.resolve(true)})
  let completed = false
  return {context,sink,complete(response:Response) {
    if (!completed) {
      completed = true
      const success = response.ok
      const finishedAt = context.now()
      const batch: WebsiteBatch = {source:'website_server',events:[{
        eventId:randomUUID(),name:`${name === 'suggestions' ? 'suggestions' : name}_finished`,schemaVersion:1,
        occurredAt:new Date(finishedAt).toISOString(),subjectId:context.visitorId,subjectKind:'visitor',operationId:context.operationId,
        properties:{outcome:success?'succeeded':'failed',durationMs:Math.min(86400000,Math.max(0,finishedAt-context.startedAt)),...(success?{}:{errorCode:'operation_failed'})},
      }]}
      enqueue(()=>sendMetrics(batch,bridge,fetchImpl))
    }
    const reply = new NextResponse(response.body,{status:response.status,headers:response.headers})
    if (name === 'analysis' && response.ok) {
      reply.headers.set('X-FitCheck-Operation-Id',context.operationId)
      reply.headers.set('access-control-expose-headers','X-FitCheck-Operation-Id')
    }
    if(visitor.isNew) setVisitorCookie(reply,visitor)
    return reply
  }}
}
