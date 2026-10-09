import type { FreelancerProfile, Job } from "@/lib/types"

export function compareHourlyRate(profile: FreelancerProfile, job: Job) {
  if (job.hourlyRateMax === undefined && job.hourlyRateMin === undefined) return "no_hourly_budget"
  if (!profile.rateCurrency || !job.budgetCurrency) return "unknown_currency"
  if (profile.rateCurrency !== job.budgetCurrency) return "conversion_required"
  if (job.hourlyRateMax === undefined) return "unknown_hourly_ceiling"
  return profile.preferredRate <= job.hourlyRateMax ? "within_budget" : "above_budget"
}
