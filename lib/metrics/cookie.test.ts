import { describe, expect, it } from 'vitest'
import { resolveVisitor, VISITOR_LIFETIME_MS } from './cookie'
describe('signed visitor', () => {
  it('test_cookie_tamper_rotates_without_trusting_claimed_visitor', () => {
    const first = resolveVisitor(undefined, 'test-secret', 1000)!
    const forged = first.cookieValue.replace(first.visitorId, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
    expect(resolveVisitor(forged, 'test-secret', 1001)!.visitorId).not.toBe('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
    expect(resolveVisitor(first.cookieValue, 'wrong-secret', 1001)!.isNew).toBe(true)
    expect(resolveVisitor(first.cookieValue, 'test-secret', 1001)!.visitorId).toBe(first.visitorId)
  })
  it('expires at original issuance without sliding and disables safely without secret', () => {
    const first = resolveVisitor(undefined, 'test-secret', 1000)!
    expect(resolveVisitor(first.cookieValue, 'test-secret', 1000 + VISITOR_LIFETIME_MS - 1)!.expiresAt).toBe(first.expiresAt)
    expect(resolveVisitor(first.cookieValue, 'test-secret', 1000 + VISITOR_LIFETIME_MS)!.visitorId).not.toBe(first.visitorId)
    expect(resolveVisitor(undefined, '', 1000)).toBeNull()
    expect(resolveVisitor(first.cookieValue, 'test-secret', 999)!.isNew).toBe(true)
  })
})
