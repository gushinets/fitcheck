// Shared transport metadata only; no server configuration or identities.
export type DeliveryResult = { delivered: boolean; retryAfterMs?: number }
export type Delivery = boolean | DeliveryResult
export const RETRY_FALLBACK_MS = 60000

export function retryAfterMs(value: string | null, now = Date.now()): number {
  const text = value?.trim() ?? ''
  if (/^\d+$/.test(text)) {
    const milliseconds = Number(text) * 1000
    return Number.isFinite(milliseconds) ? Math.max(1000, milliseconds) : Number.MAX_SAFE_INTEGER
  }
  // Accept HTTP dates, not Date.parse's permissive numeric/relative formats.
  if (/^[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(text)) {
    const date = Date.parse(text)
    if (Number.isFinite(date)) return Math.max(1000, date - now)
  }
  return RETRY_FALLBACK_MS
}
