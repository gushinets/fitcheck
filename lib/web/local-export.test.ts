import "fake-indexeddb/auto"
import { expect, it } from "vitest"
import { createWebsiteRepository } from "./repository"
import { defaultProfile, detectedJob, goAnalysis } from "@/lib/mock-data"
import * as exports from "./local-export"

it("exports only the active selected user without credentials and retains local data", async () => {
  const repo = createWebsiteRepository(`export-${crypto.randomUUID()}`)
  const a = await repo.createUser({name:"A",email:"a@example.com",password:"password-123"})
  await repo.saveProfile(a.id,defaultProfile)
  await repo.addHistory({id:"a-row",userId:a.id,profile:defaultProfile,job:detectedJob,analysis:goAnalysis,createdAt:"2025-01-01T00:00:00Z",providerOperationId:"secret-provider-id"})
  const b = await repo.createUser({name:"B",email:"b@example.com",password:"password-123"})
  await expect(repo.exportLocalData(a.id)).rejects.toThrow("selection_changed")
  const bExport = await repo.exportLocalData(b.id)
  expect(bExport.history).toEqual([])
  await repo.authenticate("a@example.com","password-123")
  const value = await repo.exportLocalData(a.id)
  expect(value.history).toHaveLength(1)
  expect(value.sourceUserId).toBe(a.id)
  expect(value.history[0]).toMatchObject({id:"a-row",profile:defaultProfile})
  for (const word of ["password","salt","email","session","providerOperationId","secret-provider-id","userId"])
    expect(JSON.stringify(value)).not.toContain(word)
  expect((await repo.loadSnapshot()).history).toHaveLength(1)
  await repo.signOut()
  await expect(repo.exportLocalData(a.id)).rejects.toThrow("selection_changed")
})

it("reads all stored history rather than the fifty-row display limit", async () => {
  const name=`export-${crypto.randomUUID()}`
  const repo=createWebsiteRepository(name)
  const u=await repo.createUser({name:"A",email:"a@example.com",password:"password-123"})
  const db=await new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open(name);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})
  await new Promise<void>((resolve,reject)=>{const t=db.transaction("history","readwrite");for(let i=0;i<60;i++)t.objectStore("history").put({id:`row-${i}`,userId:u.id,profile:defaultProfile,job:detectedJob,analysis:goAnalysis,createdAt:"2025-01-01T00:00:00Z"});t.oncomplete=()=>resolve();t.onerror=()=>reject(t.error)})
  expect((await repo.loadSnapshot()).history).toHaveLength(50)
  expect((await repo.exportLocalData(u.id)).history).toHaveLength(60)
  db.close()
})

it("batches by UTF-8 bytes without truncating or splitting a row",()=>{
  const value={version:1 as const,source:"website_indexeddb_v1" as const,sourceUserId:"a",history:Array.from({length:5},(_,i)=>({id:`${i}`,raw:"ю".repeat(50)}))}
  const batches=exports.batchLocalExport(value,400)
  expect(batches.length).toBeGreaterThan(1)
  expect(batches.flatMap(b=>b.history)).toEqual(value.history)
  expect(batches.every(b=>new TextEncoder().encode(JSON.stringify(b)).length<=400)).toBe(true)
  expect(exports.batchLocalExport(value,400)).toEqual(batches)
  expect(()=>exports.batchLocalExport(value,50)).toThrow("export_too_large")
  expect(()=>exports.batchLocalExport({...value,history:Array.from({length:1001},(_,i)=>({id:`${i}`}))},5*1024*1024)).toThrow("export_too_large")
})

it("normalizes legacy profiles, preserves feedback and reports malformed rows without copying them",()=>{
  const legacy={...defaultProfile,desiredMonthlyIncome:8000} as Record<string,unknown>
  delete legacy.workFormats
  const job={...detectedJob};delete job.url
  const value=exports.buildLocalExport("a",legacy,"ru",[
    {id:"ok",userId:"a",profile:legacy as never,job,analysis:goAnalysis,createdAt:"2025-01-01T00:00:00Z",feedback:{correctedScore:50,note:"old feedback",createdAt:"2025-01-02T00:00:00Z"}},
    {id:"bad",userId:"a",job:{password:"secret"} as never,analysis:goAnalysis,createdAt:"bad"} as never,
  ])
  expect(value.profile).toMatchObject({workFormats:["remote"]})
  expect(value.profile).not.toHaveProperty("desiredMonthlyIncome")
  expect(value.history[1]).toMatchObject({id:"ok",feedback:{correctedScore:50},job:{title:job.title}})
  expect(value.history[1].job).not.toHaveProperty("url")
  expect(value.history[0]).toEqual({id:"bad",invalid:true})
  expect(JSON.stringify(value)).not.toContain("secret")
})

it("keeps the memory repository export consistent with IndexedDB",async()=>{
  const {createMemoryWebsiteRepository}=await import("./memory-repository")
  const repo=createMemoryWebsiteRepository()
  const user=await repo.createUser({name:"A",email:"a@example.com",password:"password-123"})
  expect((await repo.exportLocalData(user.id)).history).toEqual([])
})
