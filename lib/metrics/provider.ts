import OpenAI from 'openai'
import { randomUUID } from 'node:crypto'
import type { components } from '@/lib/backend/generated/schema'
import type { OperationContext } from './operations'
export type ProviderAttempt = components['schemas']['WebsiteAttempt']
export type ProviderUsage = Pick<ProviderAttempt,'model'|'inputTokens'|'outputTokens'|'cachedInputTokens'|'cacheWriteTokens'|'reasoningTokens'|'cost'|'currency'|'costBasis'|'rateVersion'>
export interface ProviderAttemptSink { start(call:ProviderAttempt):Promise<void>; finish(call:ProviderAttempt):Promise<void> }
export function createProviderAttemptSink(_context:OperationContext, bridge:(call:ProviderAttempt)=>Promise<boolean>):ProviderAttemptSink {
  const send = async(call:ProviderAttempt)=>{try {await bridge(call)} catch {/* Best effort; never change provider outcome. */}}
  return {start:send,finish:send}
}
function safelySend(sink:ProviderAttemptSink,method:'start'|'finish',call:ProviderAttempt) {
  try { void Promise.resolve(sink[method](call)).catch(()=>{}) } catch {/* Also tolerate custom synchronous sinks. */}
}
function failureCode(error:unknown) {
  const value = error as {status?:number;name?:string;code?:string} | null
  if(value?.status === 429) return 'rate_limit'
  if(error instanceof OpenAI.APIConnectionTimeoutError || value?.status === 408 || value?.name === 'AbortError' || value?.name === 'APIConnectionTimeoutError' || value?.code === 'ETIMEDOUT') return 'timeout'
  return 'upstream'
}
export async function recordProviderCall<T>(options:{context:OperationContext;purpose:ProviderAttempt['purpose'];ordinal:number;send:()=>Promise<T>;summarize:(result:T)=>ProviderUsage;sink:ProviderAttemptSink;model?:string}):Promise<T> {
  const {context,sink}=options
  const call:ProviderAttempt={callId:randomUUID(),operationId:context.operationId,subjectId:context.visitorId,
    purpose:options.purpose,ordinal:options.ordinal,provider:'deepseek',model:options.model ?? 'deepseek-v4-flash',
    promptVersion:'website.v1',policyVersion:'grounding.v1',startedAt:new Date(context.now()).toISOString(),state:'started',costBasis:'unknown'}
  safelySend(sink,'start',call)
  let result:T
  try {result=await options.send()} catch(error) {
    safelySend(sink,'finish',{...call,state:failureCode(error) === 'timeout' || error instanceof OpenAI.APIConnectionError ? 'unknown':'failed',finishedAt:new Date(Math.max(Date.parse(call.startedAt),context.now())).toISOString(),errorCode:failureCode(error)})
    throw error
  }
  let usage:ProviderUsage = {model:call.model,cost:null,currency:null,costBasis:'unknown',inputTokens:null,outputTokens:null}
  try {usage=options.summarize(result)} catch {/* Missing or malformed usage is unknown. */}
  // Whitelist fields so a custom summarizer cannot serialize output or credentials.
  safelySend(sink,'finish',{...call,state:'succeeded',finishedAt:new Date(Math.max(Date.parse(call.startedAt),context.now())).toISOString(),
    inputTokens:usage.inputTokens,outputTokens:usage.outputTokens,cachedInputTokens:usage.cachedInputTokens,
    cacheWriteTokens:usage.cacheWriteTokens,reasoningTokens:usage.reasoningTokens,cost:usage.cost,currency:usage.currency,costBasis:usage.costBasis,rateVersion:usage.rateVersion})
  return result
}
const tokens=(value:unknown)=>typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 100000000 ? value : null
export function summarizeDeepSeek(response:unknown,model:string):ProviderUsage {
  const r=response as {usage?:{prompt_tokens?:number;completion_tokens?:number;prompt_cache_hit_tokens?:number;prompt_tokens_details?:{cached_tokens?:number};completion_tokens_details?:{reasoning_tokens?:number}}}
  const usage=r?.usage
  const input=tokens(usage?.prompt_tokens), output=tokens(usage?.completion_tokens)
  const cached=tokens(usage?.prompt_cache_hit_tokens ?? usage?.prompt_tokens_details?.cached_tokens)
  const reasoning=tokens(usage?.completion_tokens_details?.reasoning_tokens)
  return {model,inputTokens:input,outputTokens:output,cachedInputTokens:input !== null && cached !== null && cached > input ? null:cached,
    cacheWriteTokens:null,reasoningTokens:output !== null && reasoning !== null && reasoning > output ? null:reasoning,cost:null,currency:null,costBasis:'unknown',rateVersion:null}
}
