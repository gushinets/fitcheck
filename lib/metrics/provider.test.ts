// @vitest-environment node
import { expect, it, vi } from 'vitest'
import OpenAI from 'openai'
import { createWebsiteOperation } from './operations'
import { recordProviderCall, summarizeDeepSeek, summarizeOpenAI, createProviderAttemptSink } from './provider'
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
it.each([
  {prompt_cache_hit_tokens:3,completion_tokens_details:{reasoning_tokens:2}},
  {prompt_tokens_details:{cached_tokens:3},completion_tokens_details:{reasoning_tokens:2}},
])('preserves supplied partial token subdivisions without inventing totals', usage=>{
  expect(summarizeDeepSeek({usage},'deepseek-v4-flash')).toMatchObject({
    inputTokens:null,outputTokens:null,cachedInputTokens:3,reasoningTokens:2,cost:null,costBasis:'unknown',
  })
})
it('drops contradictory supplied subdivisions only when their totals are known',()=>{
  expect(summarizeDeepSeek({usage:{prompt_tokens:2,completion_tokens:1,prompt_cache_hit_tokens:3,completion_tokens_details:{reasoning_tokens:2}}},'deepseek-v4-flash')).toMatchObject({
    inputTokens:2,outputTokens:1,cachedInputTokens:null,reasoningTokens:null,cost:null,costBasis:'unknown',
  })
})
it('OpenAI usage ignores DeepSeek-only cache fields and preserves unknown cost',()=>{
  expect(summarizeOpenAI({usage:{prompt_tokens:12,completion_tokens:4,prompt_cache_hit_tokens:9,prompt_tokens_details:{cached_tokens:3},completion_tokens_details:{reasoning_tokens:0}}},'gpt-6-luna')).toMatchObject({model:'gpt-6-luna',inputTokens:12,outputTokens:4,cachedInputTokens:3,reasoningTokens:0,cost:null,costBasis:'unknown'})
  expect(summarizeOpenAI({},'gpt-6-luna')).toMatchObject({inputTokens:null,outputTokens:null,cachedInputTokens:null,reasoningTokens:null,cost:null,costBasis:'unknown'})
})
it('prices cache writes exactly and uses actual response tier',()=>{
  const r={model:'gpt-6-luna',service_tier:'default',usage:{prompt_tokens:1,completion_tokens:0,prompt_tokens_details:{cached_tokens:0,cache_write_tokens:1},completion_tokens_details:{reasoning_tokens:0}}}
  expect(summarizeOpenAI(r,'gpt-6-luna')).toMatchObject({cost:'0.000000125',currency:'USD',costBasis:'estimated',cacheWriteTokens:1,rateVersion:'openai.luna.2026-10-16',serviceTier:'default',processingRegion:'global',responseModel:'gpt-6-luna',costReason:null})
  expect(summarizeOpenAI({...r,service_tier:'flex'},'gpt-6-luna')).toMatchObject({cost:null,costBasis:'unknown',costReason:'unsupported_service_tier'})
  expect(summarizeOpenAI({...r,model:'another-model'},'gpt-6-luna')).toMatchObject({cost:null,costReason:'unsupported_model'})
  expect(summarizeOpenAI({...r,usage:{...r.usage,prompt_tokens:true}},'gpt-6-luna')).toMatchObject({inputTokens:null,cost:null,costReason:'invalid_usage'})
})
