import { z } from "zod"
import { fitAnalysisSchema, freelancerProfileSchema, jobSchema } from "@/lib/analysis/schema"

export const sessionSchema = z.object({
  user: z.object({ id: z.string().min(1), email: z.email(), emailVerified: z.boolean() }),
  csrfToken: z.string().min(1),
})
export const csrfSchema = z.object({ csrfToken: z.string().min(1) })
export const profileResourceSchema = z.object({ revision: z.string().min(1), profile: freelancerProfileSchema })
export const preferencesSchema = z.object({ locale: z.enum(["en", "ru"]) })
export const serverVacancySchema = jobSchema.extend({
  proposalCount: z.number().int().nonnegative().nullable().optional(),
  averageBid: z.number().nonnegative().nullable().optional(),
  averageBidCurrency: z.enum(["USD", "EUR", "RUB"]).nullable().optional(),
  provenance: z.record(z.string(), z.enum(["json_ld", "html", "text"])).optional(),
})
export const serverAnalysisSchema = fitAnalysisSchema.extend({
  verdictThreshold: z.number().int().min(0).max(100).optional(),
  fitCondition: z.string().max(300).nullable().optional(),
})
export const analysisResourceSchema = z.object({
  analysisId: z.string().min(1), createdAt: z.iso.datetime({ offset: true }), analysis: serverAnalysisSchema,
  snapshot: z.object({ profileRevision: z.string().nullable(), profile: freelancerProfileSchema.nullable().optional(), vacancy: serverVacancySchema }),
  feedback: z.object({ correctedScore: z.number().int().min(0).max(100), note: z.string().optional() }).nullable().optional(),
  applicationStatus: z.enum(["not_applied", "applied", "replied", "interview", "rejected", "hired"]),
  profileChanged: z.boolean().nullable().optional(),
})
export type ServerAnalysisResource = z.infer<typeof analysisResourceSchema>
export const historyPageSchema = z.object({ items: z.array(analysisResourceSchema), hasMore: z.boolean(), nextCursor: z.string().nullable() })
export const draftResourceSchema = z.object({ vacancy: serverVacancySchema, locale: z.enum(["en", "ru"]) }).nullable()
export const admissionSchema = z.object({ jobId: z.string().min(1) })
const jobBase = { jobId: z.string().min(1), type: z.enum(["analysis", "skill_suggestions"]) }
export const jobStateSchema = z.union([
  z.object({ ...jobBase, status: z.literal("queued") }),
  z.object({ ...jobBase, status: z.literal("running") }),
  z.object({ jobId: jobBase.jobId, type: z.literal("analysis"), status: z.literal("succeeded"), analysisId: z.string(), result: analysisResourceSchema }),
  z.object({ jobId: jobBase.jobId, type: z.literal("skill_suggestions"), status: z.literal("succeeded"), skills: z.array(z.string()).max(10) }),
  z.object({ ...jobBase, status: z.literal("failed"), error: z.object({ code: z.string() }) }),
])
export const importStateSchema = z.object({
  importId: z.string(), status: z.enum(["queued", "running", "succeeded", "failed"]),
  report: z.object({ importedCount: z.number(), skippedCount: z.number(), conflictCount: z.number(), invalidCount: z.number() }).optional(),
  error: z.object({ code: z.string() }).optional(),
})
