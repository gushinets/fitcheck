import type { AnalysisRequest } from "@/lib/types"

export interface AnalysisPrompt {
  instructions: string
  input: string
}

function value(value: string | number | undefined) {
  return value === undefined || value === "" ? "not provided" : String(value)
}

export function buildAnalysisPrompt(request: AnalysisRequest): AnalysisPrompt {
  const { profile, job, memory, locale } = request
  const language = locale === "ru" ? "Russian" : "English"
  const memoryText = memory.length
    ? memory
        .map(
          (entry, index) =>
            [
              `Calibration ${index + 1}: ${entry.jobTitle}`,
              `Predicted score: ${entry.predictedScore}`,
              `User-corrected score: ${value(entry.correctedScore)}`,
              `User note: ${value(entry.note)}`,
            ].join("\n"),
        )
        .join("\n\n")
    : "No prior calibration is available."

  return {
    instructions: [
      "You assess whether an Upwork job fits one freelancer profile.",
      "Score only the supplied evidence. Never invent missing requirements or credentials.",
      "Return exactly three strengths and no more than three risks.",
      "A score of 70 or higher means GO; every lower score means NO_GO.",
      `Write all user-visible fields in ${language}.`,
    ].join(" "),
    input: [
      "SYSTEM — FREELANCER PROFILE",
      `Specialization: ${profile.specialization}`,
      `Skills: ${profile.skills.join(", ")}`,
      `Experience: ${profile.experienceYears} years`,
      `Preferred hourly rate: $${profile.preferredRate}`,
      `English level: ${profile.englishLevel}`,
      "",
      "CONTEXT — CURRENT UPWORK JOB",
      `Title: ${job.title}`,
      `Description: ${job.description}`,
      `Skills: ${job.skills.length ? job.skills.join(", ") : "not provided"}`,
      `Hourly rate: ${
        job.hourlyRateMin === undefined
          ? "not provided"
          : `$${job.hourlyRateMin}–$${job.hourlyRateMax ?? job.hourlyRateMin}`
      }`,
      `Fixed budget: ${job.fixedBudget === undefined ? "not provided" : `$${job.fixedBudget}`}`,
      `Experience level: ${value(job.experienceLevel)}`,
      `Posted: ${value(job.postedAgo)}`,
      `Client rating: ${value(job.clientRating)}`,
      `Client spend: ${job.clientSpend === undefined ? "not provided" : `$${job.clientSpend}`}`,
      "",
      "TASK",
      "Evaluate skills, experience, rate, English demands, and other requirements. Return the fit analysis schema.",
      "",
      "MEMORY — USER CALIBRATION",
      "Use memory only to calibrate this user's preferences; do not treat prior jobs as facts about the current job.",
      memoryText,
    ].join("\n"),
  }
}
