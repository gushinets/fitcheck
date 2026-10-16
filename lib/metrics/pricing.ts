/** Immutable text-only Standard/global estimate, verified 2026-10-16.
 * https://developers.openai.com/api/docs/pricing
 * https://developers.openai.com/api/docs/models/gpt-6-luna
 * USD/1M input .10, cached .01, cache writes .125, output .50.
 * Unsupported premiums: >272K input 2x input/cache/write and 1.5x output;
 * regional/FedRAMP +10%. Other tiers/modalities are deliberately unknown.
 */
export const RATE_VERSION='openai.luna.2026-10-16'
export interface PricingUsage {input_tokens?:unknown;output_tokens?:unknown;cached_input_tokens?:unknown;cache_write_tokens?:unknown;reasoning_tokens?:unknown;total_tokens?:unknown;input_audio_tokens?:unknown;output_audio_tokens?:unknown;input_image_tokens?:unknown}
export interface PricingContext {model:unknown;rate_version:unknown;service_tier:unknown;processing_region:unknown}
export interface CostEstimate {amount:string|null;currency:'USD'|null;basis:'estimated'|'unknown';rate_version:string|null;reason:string|null}
export function estimateOpenAICost(usage:PricingUsage,context:PricingContext):CostEstimate {
  const unknown=(reason:string):CostEstimate=>({amount:null,currency:null,basis:'unknown',rate_version:context.rate_version===RATE_VERSION ? RATE_VERSION:null,reason})
  if(context.model!=='gpt-6-luna') return unknown('unsupported_model')
  if(context.rate_version!==RATE_VERSION) return unknown('unsupported_rate_version')
  if(context.service_tier!=='default') return unknown('unsupported_service_tier')
  if(context.processing_region!=='global') return unknown('unsupported_processing_region')
  const counts=[usage.input_tokens,usage.output_tokens,usage.cached_input_tokens,usage.cache_write_tokens,usage.reasoning_tokens,usage.total_tokens,usage.input_audio_tokens,usage.output_audio_tokens,usage.input_image_tokens]
  if(counts.some(v=>v!=null && (typeof v!=='number' || !Number.isSafeInteger(v) || v<0 || v>100000000))) return unknown('invalid_usage')
  const [total,output,cached,write,reasoning,aggregate,inputAudio,outputAudio,inputImage]=counts as (number|undefined|null)[]
  if(total==null || output==null) return unknown('missing_usage')
  if(aggregate!=null && aggregate!==total+output) return unknown('invalid_usage')
  if((inputAudio ?? 0)>0 || (outputAudio ?? 0)>0 || (inputImage ?? 0)>0) return unknown('unsupported_modality')
  if(cached==null || write==null) return unknown('missing_cache_usage')
  if(cached+write>total || (reasoning!=null && reasoning>output)) return unknown('invalid_usage')
  if(total>272000) return unknown('unsupported_large_context')
  const nano=BigInt(total-cached-write)*BigInt(100)+BigInt(cached)*BigInt(10)+BigInt(write)*BigInt(125)+BigInt(output)*BigInt(500)
  const amount=`${nano/BigInt(1000000000)}.${(nano%BigInt(1000000000)).toString().padStart(9,'0')}`
  return {amount,currency:'USD',basis:'estimated',rate_version:RATE_VERSION,reason:null}
}
