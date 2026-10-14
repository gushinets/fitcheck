// @vitest-environment node
import { expect, it, vi } from 'vitest'
import OpenAI from 'openai'
import { createWebsiteOperation } from './operations'
import { recordProviderCall, summarizeDeepSeek, createProviderAttemptSink } from './provider'
const context = () => createWebsiteOperation({ visitorId: '11111111-1111-4111-8111-111111111111', environment: 'test', name: 'analysis', now: Date.now })
it('test_collector_down_preserves_analysis_response_and_original_error', async () => {
  const sink = { start: vi.fn(() => new Promise<void>(() => {})), finish: vi.fn().mockRejectedValue(new Error('secret')) }
  const ctx = context()
  const result = { secret: 'output' }
  expect(await recordProviderCall({context:ctx,purpose:'analysis.generate',ordinal:1,send:async()=>result,summarize:()=>summarizeDeepSeek({},'deepseek-v4-flash'),sink})).toBe(result)
  const original = new Error('secret prompt key')
  await expect(recordProviderCall({context:ctx,purpose:'analysis.generate',ordinal:2,send:async()=>{throw original},summarize:()=>summarizeDeepSeek({},'deepseek-v4-flash'),sink})).rejects.toBe(original)
})
it('test_no_prompt_response_or_key_in_attempt_payload', async () => {
  const send = vi.fn().mockResolvedValue(true)
  const ctx = context(), sink = createProviderAttemptSink(ctx, send)
  await recordProviderCall({context:ctx,purpose:'analysis.generate',ordinal:1,send:async()=>({prompt:'private',choices:['private'],key:'private',usage:{prompt_tokens:12,completion_tokens:3}}),summarize:r=>summarizeDeepSeek(r,'deepseek-v4-flash'),sink})
  await Promise.resolve()
  expect(JSON.stringify(send.mock.calls)).not.toContain('private')
  expect(send.mock.calls[0][0].callId).toBe(send.mock.calls[1][0].callId)
})
it('test_missing_usage_is_unknown_not_zero', () => {
  expect(summarizeDeepSeek({},'deepseek-v4-flash')).toMatchObject({inputTokens:null,outputTokens:null,cost:null,costBasis:'unknown'})
  expect(summarizeDeepSeek({usage:{prompt_tokens:12,completion_tokens:4,prompt_cache_hit_tokens:3,completion_tokens_details:{reasoning_tokens:2}}},'deepseek-v4-flash')).toMatchObject({inputTokens:12,outputTokens:4,cachedInputTokens:3,reasoningTokens:2})
})
it.each([Object.assign(new Error('private upstream response'),{name:'AbortError'}),new OpenAI.APIConnectionTimeoutError()])('uncertain provider timeout remains unknown with a safe code',async(original)=>{
  const sink={start:vi.fn(async()=>{}),finish:vi.fn(async()=>{})}
  await expect(recordProviderCall({context:context(),purpose:'analysis.generate',ordinal:1,send:async()=>{throw original},summarize:()=>summarizeDeepSeek({},'deepseek-v4-flash'),sink})).rejects.toBe(original)
  expect(sink.finish).toHaveBeenCalledWith(expect.objectContaining({state:'unknown',errorCode:'timeout'}))
  expect(JSON.stringify(sink.finish.mock.calls)).not.toContain('private')
})
