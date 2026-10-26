import type { components } from "./generated/schema"

type Assert<T extends true> = T
type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false
type Profile = components["schemas"]["FreelancerProfile"]
type Job = components["schemas"]["JobState"]

/** Compile-time checks of generator semantics; no handwritten copies of DTOs. */
export type ContractAssertions = [
  Assert<Equal<Profile["rateCurrency"], "USD" | "EUR" | "RUB" | undefined>>,
  Assert<Equal<"desiredMonthlyIncome" extends keyof Profile ? true : false, false>>,
  Assert<Equal<Extract<Job, { type: "analysis"; status: "succeeded" }>["analysisId"], string>>,
  Assert<Equal<Extract<Job, { type: "skill_suggestions"; status: "succeeded" }>["skills"], string[]>>,
  Assert<Equal<Extract<Job, { status: "queued" }>["type"], "analysis" | "skill_suggestions">>,
]
