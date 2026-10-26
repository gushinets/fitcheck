import { z } from 'zod'
import type { components } from '@/lib/backend/generated/schema'

type Contract = components['schemas']
type OptionalProperties<T> = { [K in keyof T]?: T[K] }
export interface ClientProperties {
  page_viewed: OptionalProperties<Contract['PageProperties']>
  session_started: Contract['EmptyProperties']
  visible_activity: Contract['ActivityProperties']
  local_registration_completed: OptionalProperties<Contract['LocaleProperties']>
  local_login_completed: OptionalProperties<Contract['LocaleProperties']>
  profile_saved: OptionalProperties<Contract['LocaleProperties']>
  vacancy_input_started: OptionalProperties<Contract['InputProperties']>
  extraction_requested: OptionalProperties<Contract['InputProperties']>
  analysis_requested: OptionalProperties<Contract['InputProperties']>
  analysis_result_viewed: Pick<Contract['ResultProperties'], 'resultId'> & OptionalProperties<Omit<Contract['ResultProperties'], 'resultId'>>
  skills_requested: OptionalProperties<Contract['LocaleProperties']>
  skills_accepted: OptionalProperties<Contract['SkillsProperties']>
  history_viewed: Contract['EmptyProperties']
  feedback_saved: Contract['FeedbackProperties']
  history_cleared: Contract['EmptyProperties']
  local_account_deleted: Contract['EmptyProperties']
}
export type MetricsObserver = <N extends ClientEventName>(name: N, properties: ClientProperties[N], context?: ClientContext) => void
export type ClientEventName = keyof ClientProperties
export type ClientContext = Pick<Contract['MetricEvent'], 'operationId'>
export const clientContextSchema = z.strictObject({ operationId: z.string().uuid().nullable().optional() })
export type ClientEvent = Omit<Contract['MetricEvent'], 'name' | 'properties' | 'subjectId' | 'subjectKind' | 'domainKey'> & {
  name: ClientEventName
  properties: ClientProperties[ClientEventName]
}
export type WebsiteBatch = Contract['WebsiteBatch']
export type MetricsEnvironment = 'development' | 'production' | 'test'
export const MAX_BATCH_BYTES = 32 * 1024
export const MAX_BATCH_EVENTS = 20
export const uuidSchema = z.string().uuid()
const locale = z.enum(['en', 'ru']).nullable().optional()
const empty = z.strictObject({})
const localized = z.strictObject({ locale })
const score = z.number().int().min(0).max(100)
const flow = z.enum(['demo', 'account']).nullable().optional()
const requestId = uuidSchema.nullable().optional()
const input = z.strictObject({ locale, flow, requestId, inputMode: z.enum(['url', 'text']).nullable().optional(), platform: z.enum(['freelancer', 'upwork', 'other', 'text']).nullable().optional() })
const result = input.extend({ resultId: uuidSchema, predictedScore: score.nullable().optional() })
export const clientPropertySchemas = {
  page_viewed: z.strictObject({ locale, campaign: z.string().regex(/^[a-z][a-z0-9_]{0,79}$/).nullable().optional() }),
  session_started: empty,
  visible_activity: z.strictObject({ activeMs: z.number().int().min(0).max(30000) }),
  local_registration_completed: localized, local_login_completed: localized, profile_saved: localized,
  vacancy_input_started: input, extraction_requested: input, analysis_requested: input,
  analysis_result_viewed: result, skills_requested: localized,
  skills_accepted: z.strictObject({ locale, count: z.number().int().min(0).max(10).nullable().optional() }),
  history_viewed: empty,
  feedback_saved: z.strictObject({ resultId: uuidSchema, predictedScore: score, correctedScore: score }),
  history_cleared: empty, local_account_deleted: empty,
} satisfies { [N in ClientEventName]: z.ZodType<ClientProperties[N]> }
const envelope = z.strictObject({
  eventId: uuidSchema, name: z.string(), schemaVersion: z.literal(1),
  occurredAt: z.iso.datetime({ offset: true }), sessionId: uuidSchema.nullable().optional(),
  operationId: uuidSchema.nullable().optional(), properties: z.record(z.string(), z.unknown()),
})
export function validateClientEvent(value: unknown): ClientEvent | null {
  const parsed = envelope.safeParse(value)
  if (!parsed.success || !Object.hasOwn(clientPropertySchemas, parsed.data.name)) return null
  const name = parsed.data.name as ClientEventName
  const properties = clientPropertySchemas[name].safeParse(parsed.data.properties)
  return properties.success ? { ...parsed.data, name, properties: properties.data } as ClientEvent : null
}
