import OpenAI from 'openai'
import { estimateOpenAICost, RATE_VERSION } from './pricing'
import { randomUUID } from 'node:crypto'
import type { components } from '@/lib/backend/generated/schema'
import type { OperationContext } from './operations'
export type ProviderAttempt = components['schemas']['WebsiteAttempt']
export type ProviderUsage = Pick<ProviderAttempt,'model'|'inputTokens'|'outputTokens'|'cachedInputTokens'|'cacheWriteTokens'|'reasoningTokens'|'cost'|'currency'|'costBasis'|'rateVersion'|'costReason'|'serviceTier'|'processingRegion'|'responseModel'>
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
export async function recordProviderCall<T>(options:{context:OperationContext;purpose:ProviderAttempt['purpose'];ordinal:number;send:()=>Promise<T>;summarize:(result:T)=>ProviderUsage;sink:ProviderAttemptSink;model?:string;provider?:ProviderAttempt['provider'];policyVersion?:string}):Promise<T> {
  const {context,sink}=options
  const call:ProviderAttempt={callId:randomUUID(),operationId:context.operationId,subjectId:context.visitorId,
    purpose:options.purpose,ordinal:options.ordinal,provider:options.provider ?? 'deepseek',model:options.model ?? 'deepseek-v4-flash',
    promptVersion:'website.v1',policyVersion:options.policyVersion ?? 'grounding.v1',startedAt:new Date(context.now()).toISOString(),state:'started',costBasis:'unknown'}
  safelySend(sink,'start',call)
  let result:T
  try {result=await options.send()} catch(error) {
    safelySend(sink,'finish',{...call,state:failureCode(error) === 'timeout' || error instanceof OpenAI.APIConnectionError ? 'unknown':'failed',finishedAt:new Date(Math.max(Date.parse(call.startedAt),context.now())).toISOString(),errorCode:failureCode(error),costReason:'missing_usage'})
    throw error
  }
  let usage:ProviderUsage = {model:call.model,cost:null,currency:null,costBasis:'unknown',inputTokens:null,outputTokens:null,costReason:'missing_usage'}
  try {usage=options.summarize(result)} catch {/* Missing or malformed usage is unknown. */}
  // Whitelist fields so a custom summarizer cannot serialize output or credentials.
  safelySend(sink,'finish',{...call,state:'succeeded',finishedAt:new Date(Math.max(Date.parse(call.startedAt),context.now())).toISOString(),
    inputTokens:usage.inputTokens,outputTokens:usage.outputTokens,cachedInputTokens:usage.cachedInputTokens,
    cacheWriteTokens:usage.cacheWriteTokens,reasoningTokens:usage.reasoningTokens,cost:usage.cost,currency:usage.currency,costBasis:usage.costBasis,rateVersion:usage.rateVersion,
    costReason:usage.costReason,serviceTier:usage.serviceTier,processingRegion:usage.processingRegion,responseModel:usage.responseModel})
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

// The fixed api.openai.com transport has global processing. Never infer actual
// service tier from the request/project default, or missing cache counts as zero.
export function summarizeOpenAI(response:unknown,model:string):ProviderUsage {
  const value=response as {model?:unknown;service_tier?:unknown;usage?:{prompt_tokens?:unknown;completion_tokens?:unknown;total_tokens?:unknown;prompt_tokens_details?:{cached_tokens?:unknown;cache_write_tokens?:unknown;audio_tokens?:unknown;image_tokens?:unknown};completion_tokens_details?:{reasoning_tokens?:unknown;audio_tokens?:unknown}}}|null
  const raw=value?.usage
  const estimate=estimateOpenAICost({input_tokens:raw?.prompt_tokens,output_tokens:raw?.completion_tokens,
    cached_input_tokens:raw?.prompt_tokens_details?.cached_tokens,cache_write_tokens:raw?.prompt_tokens_details?.cache_write_tokens,
    reasoning_tokens:raw?.completion_tokens_details?.reasoning_tokens,total_tokens:raw?.total_tokens,
    input_audio_tokens:raw?.prompt_tokens_details?.audio_tokens,output_audio_tokens:raw?.completion_tokens_details?.audio_tokens,input_image_tokens:raw?.prompt_tokens_details?.image_tokens},
    {model:value?.model,rate_version:RATE_VERSION,service_tier:value?.service_tier,processing_region:'global'})
  const input=tokens(raw?.prompt_tokens),output=tokens(raw?.completion_tokens)
  let cached=tokens(raw?.prompt_tokens_details?.cached_tokens),write=tokens(raw?.prompt_tokens_details?.cache_write_tokens)
  let reasoning=tokens(raw?.completion_tokens_details?.reasoning_tokens)
  if(input!==null && (cached ?? 0)+(write ?? 0)>input) cached=write=null
  if(output!==null && reasoning!==null && reasoning>output) reasoning=null
  const metadata=(v:unknown,pattern:RegExp)=>typeof v==='string' && pattern.test(v) ? v:null
  return {model,inputTokens:input,outputTokens:output,cachedInputTokens:cached,cacheWriteTokens:write,reasoningTokens:reasoning,
    cost:estimate.amount,currency:estimate.currency,costBasis:estimate.basis,rateVersion:estimate.rate_version,costReason:estimate.reason,
    serviceTier:metadata(value?.service_tier,/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,39}$/),processingRegion:'global',responseModel:metadata(value?.model,/^[a-z][a-z0-9._-]{0,199}$/)}
}
