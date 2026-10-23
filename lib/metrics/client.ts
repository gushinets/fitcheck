import { MAX_BATCH_BYTES, MAX_BATCH_EVENTS, clientContextSchema, validateClientEvent } from './types'
import type { ClientContext, ClientEvent, ClientEventName, ClientProperties } from './types'

interface Timers {
  setTimeout: typeof setTimeout
  clearTimeout: typeof clearTimeout
  setInterval: typeof setInterval
  clearInterval: typeof clearInterval
}
interface ClientOptions {
  send: (events: ClientEvent[], signal?: AbortSignal) => Promise<boolean>
  deleteVisitor?: (signal?: AbortSignal) => Promise<boolean>
  now?: () => number
  eventId?: () => string
  timers?: Timers
  document?: Document
}
const SESSION_IDLE = 30 * 60 * 1000
const PULSE = 30000
// Memory-only observations. This module never imports a server configuration or identity.
export function createMetricsClient(options: ClientOptions) {
  const now = options.now ?? Date.now
  const id = options.eventId ?? (() => crypto.randomUUID())
  // Browser-native timers require the global receiver when called through this object.
  const timers = options.timers ?? {
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
    setInterval: globalThis.setInterval.bind(globalThis),
    clearInterval: globalThis.clearInterval.bind(globalThis),
  }
  const doc = options.document ?? (typeof document === 'undefined' ? undefined : document)
  let queue: ClientEvent[] = []
  let session: string | undefined
  let lastActivity = -Infinity
  let activeFrom: number | undefined
  let disposed = false
  let deleting = false
  let generation = 0
  let scheduled: ReturnType<typeof setTimeout> | undefined
  let running: Promise<void> | undefined
  let inFlight = 0
  let abortDelivery: (() => void) | undefined
  let delivered = 0, failed = 0, dropped = 0
  let reportedDropped = 0
  const visible = () => !doc || doc.visibilityState === 'visible'
  const bytes = (events: ClientEvent[]) => new TextEncoder().encode(JSON.stringify({ events })).length
  function enqueue(event: ClientEvent) {
    if (bytes([event]) > MAX_BATCH_BYTES) { dropped++; return }
    if (queue.length >= 100 - inFlight) { queue.shift(); dropped++ }
    queue.push(event)
  }
  function makeEvent<N extends ClientEventName>(name: N, properties: ClientProperties[N], context: ClientContext = {}) {
    return validateClientEvent({ eventId: id(), name, properties, ...context, sessionId: session, schemaVersion: 1, occurredAt: new Date(now()).toISOString() })
  }
  function schedule() {
    if (scheduled !== undefined || disposed) return
    scheduled = timers.setTimeout(() => { scheduled = undefined; void flush() }, 0)
  }
  function activity() {
    if (disposed || deleting || !visible()) return
    const time = now()
    if (!session || time - lastActivity >= SESSION_IDLE) {
      session = id()
      const started = makeEvent('session_started', {})
      if (started) enqueue(started)
    }
    if (activeFrom === undefined || time - lastActivity > PULSE) activeFrom = time
    lastActivity = time
  }
  function track<N extends ClientEventName>(name: N, properties: ClientProperties[N], context: ClientContext = {}): boolean {
    if (disposed || deleting) return false
    // Validate before allowing the observation to start a session.
    const parsedContext = clientContextSchema.safeParse(context)
    if (!parsedContext.success) return false
    const candidate = validateClientEvent({ eventId: id(), name, properties, ...parsedContext.data, schemaVersion: 1, occurredAt: new Date(now()).toISOString() })
    if (!candidate) return false
    activity()
    candidate.sessionId = session
    enqueue(candidate)
    schedule()
    return true
  }
  async function boundedDelivery(operation: (signal: AbortSignal) => Promise<boolean>): Promise<boolean> {
    const controller = new AbortController()
    let timeout: ReturnType<typeof setTimeout> | undefined
    try {
      const deadline = new Promise<boolean>(resolve => {
        abortDelivery = () => { controller.abort(); resolve(false) }
        timeout = timers.setTimeout(abortDelivery, 2500)
      })
      const delivery = Promise.resolve().then(() => operation(controller.signal)).catch(() => false)
      return await Promise.race([delivery, deadline])
    } finally {
      if (timeout !== undefined) timers.clearTimeout(timeout)
      abortDelivery = undefined
    }
  }
  async function drain() {
    const previousFailed = failed
    const epoch = generation
    while (!disposed && epoch === generation && queue.length) {
      const batch: ClientEvent[] = []
      while (queue.length && batch.length < MAX_BATCH_EVENTS && bytes([...batch, queue[0]]) <= MAX_BATCH_BYTES) batch.push(queue.shift()!)
      if (!batch.length) { queue.shift(); dropped++; continue }
      inFlight = batch.length
      let success = false
      for (let attempt = 0; attempt < 3 && !disposed && epoch === generation; attempt++) {
        try { success = await boundedDelivery(signal => options.send(batch, signal)) } catch { success = false }
        if (success) break
      }
      inFlight = 0
      if (epoch === generation && !disposed) {
        if (success) delivered += batch.length
        else failed += batch.length
      }
    }
    if (epoch === generation && !disposed && (failed !== previousFailed || dropped !== reportedDropped)) {
      reportedDropped = dropped
      try { console.warn('fitcheck_metrics_client_loss', { failed, dropped }) } catch { /* Best effort only. */ }
    }
  }
  function flush(): Promise<void> {
    if (scheduled !== undefined) { timers.clearTimeout(scheduled); scheduled = undefined }
    if (disposed || deleting) return running ?? Promise.resolve()
    if (!running) running = drain().finally(() => { running = undefined; if (queue.length && !disposed) schedule() })
    return running
  }
  function pulse() {
    const time = now()
    if (disposed || deleting || activeFrom === undefined) return
    const end = Math.min(time, lastActivity + PULSE)
    if (visible() && end > activeFrom) {
      const event = makeEvent('visible_activity', { activeMs: Math.min(PULSE, Math.max(0, Math.floor(end - activeFrom))) })
      if (event) enqueue(event)
      schedule()
    }
    activeFrom = visible() && time < lastActivity + PULSE ? time : undefined
  }
  const observedActivity = () => { activity(); schedule() }
  const visibility = () => {
    // Only close the already observed foreground interval; never add background time.
    if (!visible()) {
      const time = now()
      if (activeFrom !== undefined) {
        const activeMs = Math.min(PULSE, Math.max(0, Math.floor(Math.min(time, lastActivity + PULSE) - activeFrom)))
        if (activeMs) { const event = makeEvent('visible_activity', { activeMs }); if (event) enqueue(event) }
      }
      activeFrom = undefined
    }
    void flush()
  }
  const interval = timers.setInterval(pulse, PULSE)
  const activityEvents = ['pointerdown', 'keydown', 'scroll', 'touchstart']
  for (const event of activityEvents) doc?.addEventListener(event, observedActivity, { passive: true })
  doc?.addEventListener('visibilitychange', visibility)
  function resetIdentity() {
    generation++
    queue = []
    session = undefined
    lastActivity = -Infinity
    activeFrom = undefined
    if (scheduled !== undefined) { timers.clearTimeout(scheduled); scheduled = undefined }
  }
  return {
    track, flush, resetIdentity,
    async deleteVisitor(): Promise<boolean> {
      if (disposed) return false
      deleting = true
      resetIdentity()
      // Settle any old POST response before rotation so it cannot restore its cookie.
      await running
      try {
        if (disposed) return false
        return await boundedDelivery(signal => options.deleteVisitor?.(signal) ?? Promise.resolve(false))
      } catch { return false }
      finally { resetIdentity(); deleting = false }
    },
    stats: () => ({ queued: queue.length, delivered, failed, dropped }),
    dispose() {
      if (disposed) return
      disposed = true
      abortDelivery?.()
      resetIdentity()
      timers.clearInterval(interval)
      for (const event of activityEvents) doc?.removeEventListener(event, observedActivity)
      doc?.removeEventListener('visibilitychange', visibility)
    },
  }
}

export async function sendBrowserMetrics(events: ClientEvent[], signal?: AbortSignal): Promise<boolean> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 2500)
  try {
    const response = await fetch('/api/metrics', { method: 'POST', signal: signal ? AbortSignal.any([signal, controller.signal]) : controller.signal, credentials: 'same-origin', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ events }) })
    if (!response.ok) return false
    return (await response.json()).delivered === true
  } catch { return false }
  finally { clearTimeout(timeout) }
}
export async function deleteBrowserVisitor(signal?: AbortSignal): Promise<boolean> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 2500)
  try {
    const response = await fetch('/api/metrics', { method: 'DELETE', signal: signal ? AbortSignal.any([signal, controller.signal]) : controller.signal, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    return response.ok && (await response.json()).delivered === true
  } catch { return false }
  finally { clearTimeout(timeout) }
}
