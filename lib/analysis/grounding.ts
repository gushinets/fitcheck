import type { AnalysisRequest } from "@/lib/types"
import { compareHourlyRate } from "./currency"
import { formatMoney } from "@/lib/currency"

export interface StrengthFact {
  id: string
  text: string
  profileFields: string[]
  taskFields: string[]
}

function mentions(text: string, value: string) {
  const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  return new RegExp(`(?<![\\p{L}\\p{N}])${escaped}(?![\\p{L}\\p{N}])`, "iu").test(text)
}

export function buildStrengthEvidence(request: AnalysisRequest): StrengthFact[] {
  const { profile, job, locale } = request
  const ru = locale === "ru"
  const facts: StrengthFact[] = []
  const taskText = `${job.title}\n${job.description}`
  const matchingFields = (pattern: RegExp) => [
    ...(pattern.test(job.title) ? ["title"] : []),
    ...(pattern.test(job.description) ? ["description"] : []),
  ]
  profile.skills.forEach((skill, index) => {
    const key = skill.trim().toLowerCase()
    const level = profile.skillLevels && Object.hasOwn(profile.skillLevels, key) ? profile.skillLevels[key] : undefined
    if (level === "basic") return
    const taskFields = [
      ...(job.skills.some((entry) => entry.trim().toLowerCase() === key) ? ["skills"] : []),
      ...(mentions(job.title, skill) ? ["title"] : []),
      ...(mentions(job.description, skill) ? ["description"] : []),
    ]
    if (!taskFields.length) return
    const proficiency = level === "primary"
      ? (ru ? "Основной навык." : "Primary skill.")
      : level === "confident" ? (ru ? "Уровень: уверенно." : "Proficiency: confident.")
        : (ru ? "Уровень владения не указан." : "Proficiency is not specified.")
    facts.push({
      id: `skill:${index}`,
      text: ru ? `В профиле указан ${skill}; этот навык упоминается в задаче. ${proficiency}` : `Your profile lists ${skill}; this skill appears in the task. ${proficiency}`,
      profileFields: [`skills.${index}`, ...(level ? [`skillLevels.${key}`] : [])], taskFields,
    })
  })
  if (profile.experienceYears > 0 && (job.experienceLevel || /experienc|опыт/i.test(taskText))) {
    facts.push({ id: "experience", text: ru ? `В профиле указан общий опыт: ${profile.experienceYears} лет. Опыт именно в этой задаче не подтверждён.` : `Your profile reports ${profile.experienceYears} years of overall experience; task-specific experience is not established.`, profileFields: ["experienceYears"], taskFields: job.experienceLevel ? ["experienceLevel"] : matchingFields(/experienc|опыт/i) })
  }
  if (/\bEnglish\b|английск/i.test(taskText)) {
    facts.push({ id: "english", text: ru ? `Указанный в профиле уровень английского: ${profile.englishLevel}.` : `Your reported English level is ${profile.englishLevel}.`, profileFields: ["englishLevel"], taskFields: matchingFields(/\bEnglish\b|английск/i) })
  }
  const remoteFields = matchingFields(/\b(?:work(?:ing)?\s+remotely|remote\s+(?:work|job|role|position)|work\s*(?:format|mode|location)\s*:\s*remote)\b|удал[её]нн\p{L}*\s+(?:работ|формат)/iu)
  if (profile.workFormats.includes("remote") && remoteFields.length) {
    facts.push({ id: "workFormat:remote", text: ru ? "Удалённый формат упоминается в задаче и выбран в профиле." : "Remote work is mentioned in the task and selected in your profile.", profileFields: ["workFormats"], taskFields: remoteFields })
  }
  if (compareHourlyRate(profile, job) === "within_budget") {
    facts.push({ id: "rate", text: ru ? `Ставка из профиля ${formatMoney(profile.preferredRate, profile.rateCurrency)}/час не превышает указанный почасовой максимум задачи.` : `Your profile rate of ${formatMoney(profile.preferredRate, profile.rateCurrency)}/hour does not exceed the task's stated hourly maximum.`, profileFields: ["preferredRate", "rateCurrency"], taskFields: ["hourlyRateMax", "budgetCurrency"] })
  }
  return facts
}
