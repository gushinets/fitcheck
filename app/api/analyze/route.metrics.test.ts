// @vitest-environment node
import { afterEach, expect, it, vi } from 'vitest'
import { defaultProfile, detectedJob, goAnalysis } from '@/lib/mock-data'
const callbacks = vi.hoisted(()=>[] as (()=>Promise<void>)[])
vi.mock('next/server',async importOriginal=>({...await importOriginal<typeof import('next/server')>(),after:(callback:()=>Promise<void>)=>callbacks.push(callback)}))
import { POST } from './route'
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();callbacks.length=0})
it.each([true,false])('server analysis success follows grounding validation (%s)',async supported=>{
  vi.stubEnv('DEEPSEEK_API_KEY','private-key')
  vi.stubEnv('METRICS_COOKIE_SECRET','test-secret')
  vi.stubEnv('METRICS_ENVIRONMENT','test')
  vi.stubEnv('METRICS_BACKEND_URL','https://metrics.example')
  vi.stubEnv('METRICS_BRIDGE_KEY','private-bridge')
  const delivered: {events?:{properties:{outcome:string}}[]}[]=[]
  vi.stubGlobal('fetch',vi.fn(async (url,init)=>{
    if(String(url).startsWith('https://metrics.example')) {delivered.push(JSON.parse(init.body)); return new Response('{}')}
    const body=JSON.parse(init.body)
    const audit=body.max_tokens===1000
    return new Response(JSON.stringify({choices:[{message:{content:JSON.stringify(audit ? {supported,unsupportedClaims:supported?[]:['invented claim']}:{...goAnalysis,strengths:[]})}}]}),{headers:{'content-type':'application/json'}})
  }))
  const response=await POST(new Request('https://app.test/api/analyze',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({profile:defaultProfile,job:detectedJob,locale:'en',memory:[]})}))
  expect(response.status).toBe(supported?200:502)
  expect(!!response.headers.get('X-FitCheck-Operation-Id')).toBe(supported)
  expect(delivered).toEqual([])
  await callbacks[0]()
  expect(delivered.find(batch=>batch.events)?.events?.[0].properties.outcome).toBe(supported?'succeeded':'failed')
  expect(JSON.stringify(delivered)).not.toContain('private-key')
  expect(JSON.stringify(delivered)).not.toContain('invented claim')
})
