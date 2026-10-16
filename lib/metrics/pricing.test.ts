import { describe, expect, it } from 'vitest'
import cases from '../../backend/tests/fixtures/openai_pricing.json'
import { estimateOpenAICost, RATE_VERSION } from './pricing'

describe('versioned OpenAI prices',()=>{
  it('matches the Python shared price fixtures exactly',()=>{
    for(const c of cases) {
      const result=estimateOpenAICost(c.usage,{model:'gpt-6-luna',rate_version:RATE_VERSION,service_tier:'default',processing_region:'global',...c.options})
      expect(result.amount,c.name).toBe(c.amount)
      expect(result.reason,c.name).toBe(c.reason ?? null)
    }
  })
  it('rejects unsafe or inconsistent usage',()=>{
    for(const usage of [{input_tokens:true,output_tokens:1,cached_input_tokens:0,cache_write_tokens:0},{input_tokens:1,output_tokens:1,cached_input_tokens:1,cache_write_tokens:1}]) {
      expect(estimateOpenAICost(usage,{model:'gpt-6-luna',rate_version:RATE_VERSION,service_tier:'default',processing_region:'global'}).reason).toBe('invalid_usage')
    }
  })
})
