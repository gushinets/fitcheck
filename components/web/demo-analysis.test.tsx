import { StrictMode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { defaultProfile, detectedJob, goAnalysis } from '@/lib/mock-data'
import type { ServerWebsite } from '@/lib/web/server'
import { WebsiteServerError } from '@/lib/web/server'
import { DemoAnalysis } from './demo-analysis'

const jobId = '11111111-1111-4111-8111-111111111111'
const resultId = '22222222-2222-4222-8222-222222222222'
const requestId = '33333333-3333-4333-8333-333333333333'
const draft = { ...detectedJob, sourceMode: 'text' as const, updatedAt: '2026-10-23T12:00:00Z' }
const completed = { jobId, analysis: goAnalysis, entry: { id: resultId, userId: 'guest', profile: defaultProfile, job: detectedJob, analysis: goAnalysis, createdAt: '2026-10-23T12:00:00Z' } }
vi.mock('./profile-editor', () => ({ ProfileEditor: ({ onSave }: { onSave: (v: unknown) => void }) => <button onClick={() => onSave(defaultProfile)}>save profile</button> }))
vi.mock('./vacancy-source', () => ({ VacancySource: ({ onInputStarted, onLoadUrl, onReview }: { onInputStarted?: (v: string) => void; onLoadUrl: (url: string) => Promise<unknown>; onReview: (v: unknown) => void }) => <>
  <button onClick={() => { onInputStarted?.('text'); onReview(draft) }}>text</button>
  <button onClick={() => { onInputStarted?.('url'); void onLoadUrl('https://private.example/secret').then(onReview).catch(() => {}) }}>url</button>
</> }))
vi.mock('./vacancy-review', () => ({ VacancyReview: ({ draft: value, onAnalyze }: { draft: unknown; onAnalyze: (v: unknown) => void }) => <button onClick={() => onAnalyze(value)}>analyze</button> }))
vi.mock('./analysis-result', () => ({ AnalysisResult: () => <div>displayed result</div> }))
function setup() {
  return {
    createGuest: vi.fn(async () => {}), hasPendingAnalysis: () => false,
    resumeAnalysis: vi.fn(async () => completed),
    analyzeGuest: vi.fn(async (_input, onRequest) => { onRequest?.(requestId); return completed }),
    api: { extractVacancy: vi.fn(async () => ({ ...draft, sourceMode: 'url' })) },
  }
}
async function analyze(mode: 'text' | 'url') {
  fireEvent.click(await screen.findByText('save profile'))
  fireEvent.click(await screen.findByText(mode))
  fireEvent.click(await screen.findByText('analyze'))
}
describe('demo observations', () => {
  it.each(['en', 'ru'] as const)('observes attempts and committed result once in %s, without private content', async locale => {
    const server = setup(); const observe = vi.fn()
    const view = render(<StrictMode><DemoAnalysis server={server as unknown as ServerWebsite} locale={locale} onAccount={() => {}} observe={observe} /></StrictMode>)
    await analyze('text')
    await screen.findByText('displayed result')
    expect(observe.mock.calls.map(c => c[0])).toEqual(['vacancy_input_started', 'analysis_requested', 'analysis_result_viewed'])
    expect(observe).toHaveBeenCalledWith('analysis_requested', { flow: 'demo', locale, inputMode: 'text', requestId })
    expect(observe).toHaveBeenCalledWith('analysis_result_viewed', expect.objectContaining({ flow: 'demo', locale, resultId }), { operationId: jobId })
    view.rerender(<StrictMode><DemoAnalysis server={server as unknown as ServerWebsite} locale={locale} onAccount={() => {}} observe={observe} /></StrictMode>)
    expect(observe.mock.calls.filter(c => c[0] === 'analysis_result_viewed')).toHaveLength(1)
    expect(JSON.stringify(observe.mock.calls)).not.toMatch(/private|secret|description|specialization/)
  })
  it('observes URL extraction separately and cannot break analysis when telemetry throws', async () => {
    const server = setup(); const observe = vi.fn((...args: unknown[]) => { throw new Error(String(args[0])) })
    render(<DemoAnalysis server={server as unknown as ServerWebsite} locale='en' onAccount={() => {}} observe={observe} />)
    await analyze('url'); await screen.findByText('displayed result')
    expect(observe.mock.calls.map(c => c[0])).toContain('extraction_requested')
    expect(server.api.extractVacancy).toHaveBeenCalledOnce()
  })
  it.each(['quota_exceeded', 'service_unavailable'])('never observes a result after %s', async code => {
    const server = setup(); const observe = vi.fn()
    server.analyzeGuest.mockImplementation(async (_input, callback) => { callback?.(requestId); throw new WebsiteServerError(code) })
    render(<DemoAnalysis server={server as unknown as ServerWebsite} locale='ru' onAccount={() => {}} observe={observe} />)
    await analyze('text'); await screen.findByRole('alert')
    expect(observe.mock.calls.map(c => c[0])).toEqual(['vacancy_input_started', 'analysis_requested'])
  })
  it('resumes polling without inventing another request, and observes a reopened view', async () => {
    const server = { ...setup(), hasPendingAnalysis: () => true }; const observe = vi.fn()
    const view = render(<DemoAnalysis server={server as unknown as ServerWebsite} locale='en' onAccount={() => {}} observe={observe} />)
    await screen.findByText('displayed result'); view.unmount()
    render(<DemoAnalysis server={server as unknown as ServerWebsite} locale='en' onAccount={() => {}} observe={observe} />)
    await screen.findByText('displayed result')
    await waitFor(() => expect(observe.mock.calls.map(c => c[0])).toEqual(['analysis_result_viewed','analysis_result_viewed']))
  })
  it('does not observe an asynchronous result after leaving the demo', async () => {
    const server = setup(); const observe = vi.fn(); let resolve!: (v: typeof completed) => void
    server.analyzeGuest.mockImplementation(async (_input, callback) => { callback?.(requestId); return new Promise(r => { resolve = r }) })
    const view = render(<DemoAnalysis server={server as unknown as ServerWebsite} locale='en' onAccount={() => {}} observe={observe} />)
    await analyze('text'); await waitFor(() => expect(server.analyzeGuest).toHaveBeenCalledOnce()); view.unmount()
    await act(async () => { resolve(completed) })
    expect(observe.mock.calls.map(c => c[0])).not.toContain('analysis_result_viewed')
  })
})
