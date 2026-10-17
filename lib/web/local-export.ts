import { z } from "zod"
import { normalizeFreelancerProfile, jobSchema, fitAnalysisSchema } from "@/lib/analysis/schema"
import type { WebHistoryEntry } from "./types"
import type { Locale } from "@/lib/types"

export interface LocalImportRequest {
  version: 1
  source: "website_indexeddb_v1"
  sourceUserId: string
  profile?: Record<string, unknown> | null
  locale?: Locale | null
  history: Record<string, unknown>[]
}

const MAX_BYTES = 5 * 1024 * 1024
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length

function profileExport(value: unknown): Record<string, unknown> | undefined {
  if (value == null) return undefined
  try { return { ...normalizeFreelancerProfile(value) } } catch { return {} }
}

const rowMetadata=z.object({
  id:z.string().trim().min(1).max(200),
  createdAt:z.iso.datetime({offset:true}),
  feedback:z.object({correctedScore:z.number().int().min(0).max(100),note:z.string().max(500).optional(),createdAt:z.iso.datetime({offset:true})}).optional(),
})

function historyExport(entry: WebHistoryEntry): Record<string, unknown> {
  const meta=rowMetadata.safeParse(entry)
  const id=typeof entry.id==="string" && entry.id.trim().length>0 && entry.id.length<=200 ? entry.id : undefined
  if(!meta.success)return { ...(id ? {id} : {}), invalid:true }
  // Parsed schemas strip unknown fields instead of copying untrusted stored objects.
  const job=jobSchema.safeParse(entry.job)
  const analysis=fitAnalysisSchema.safeParse(entry.analysis)
  if (!job.success || !analysis.success) return { id: entry.id, invalid: true }
  const feedback=meta.data.feedback
  return {
    id:meta.data.id, createdAt:meta.data.createdAt, job:job.data, analysis:analysis.data,
    ...(entry.profile == null ? {} : {profile:profileExport(entry.profile)}),
    ...(feedback ? {feedback:{correctedScore:feedback.correctedScore,note:feedback.note,createdAt:feedback.createdAt}} : {}),
  }
}

export function buildLocalExport(sourceUserId: string, profile: unknown, locale: Locale | undefined, entries: WebHistoryEntry[]): LocalImportRequest {
  const value: LocalImportRequest={version:1,source:"website_indexeddb_v1",sourceUserId,
    ...(profile == null ? {} : {profile:profileExport(profile)}), ...(locale ? {locale} : {}),
    history:[...entries].sort((a,b)=>String(a.id).localeCompare(String(b.id))).map(historyExport)}
  if(value.history.length>1000 || bytes(value)>MAX_BYTES) throw new Error("export_too_large")
  return value
}

export function batchLocalExport(value: LocalImportRequest, maxBytes: number): LocalImportRequest[] {
  const limit=Math.min(maxBytes,MAX_BYTES)
  if(!Number.isSafeInteger(limit)||limit<1||value.history.length>1000) throw new Error("export_too_large")
  const batches:LocalImportRequest[]=[]
  let batch={...value,history:[] as Record<string,unknown>[]}
  if(bytes(batch)>limit) throw new Error("export_too_large")
  for(const row of value.history){
    const candidate={...batch,history:[...batch.history,row]}
    if(bytes(candidate)<=limit){batch=candidate;continue}
    if(batch.history.length) batches.push(batch)
    batch={...value,history:[row]}
    if(bytes(batch)>limit) throw new Error("export_too_large")
  }
  if(batch.history.length||batches.length===0)batches.push(batch)
  return batches
}
