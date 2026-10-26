import { describe, expect, it } from 'vitest'
import { validateClientEvent, clientPropertySchemas } from './types'
const event = (name: string, properties: unknown) => ({ eventId: crypto.randomUUID(), name, schemaVersion: 1, occurredAt: new Date().toISOString(), properties })
describe('client registry', () => {
  it('matches every client event and rejects unknown facts, properties and malformed context', () => {
    expect(Object.keys(clientPropertySchemas)).toHaveLength(16)
    expect(validateClientEvent(event('analysis_finished', {}))).toBeNull()
    expect(validateClientEvent(event('page_viewed', { campaign: 'raw?secret=1' }))).toBeNull()
    expect(validateClientEvent(event('page_viewed', { locale: 'de' }))).toBeNull()
    expect(validateClientEvent({ ...event('page_viewed', {}), operationId: 'raw-content' })).toBeNull()
    expect(validateClientEvent({ ...event('page_viewed', {}), occurredAt: 'invalid' })).toBeNull()
    expect(validateClientEvent({ ...event('page_viewed', {}), schemaVersion: 2 })).toBeNull()
  })
  it('allows bounded integer scores and strict registry-specific fields only', () => {
    const resultId = crypto.randomUUID()
    for (const score of [0, 100]) expect(validateClientEvent(event('feedback_saved', { resultId, predictedScore: score, correctedScore: score }))).not.toBeNull()
    for (const score of [-1, 101, 3.5, '5']) expect(validateClientEvent(event('feedback_saved', { resultId, predictedScore: score, correctedScore: 50 }))).toBeNull()
    expect(validateClientEvent(event('visible_activity', { activeMs: 30001 }))).toBeNull()
    expect(validateClientEvent(event('skills_accepted', { count: 11 }))).toBeNull()
    expect(validateClientEvent(event('history_viewed', { note: 'private' }))).toBeNull()
  })
})
