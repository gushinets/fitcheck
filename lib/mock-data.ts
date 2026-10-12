import type {
  FitAnalysis,
  FreelancerProfile,
  Job,
} from "./types"

export const defaultProfile: FreelancerProfile = {
  specialization: "Backend Developer",
  skills: ["Python", "Django", "FastAPI", "PostgreSQL", "Docker"],
  experienceYears: 5,
  preferredRate: 35,
  workFormats: ["remote", "hybrid"],
  englishLevel: "Upper Intermediate",
}

/** A public task fixture used by website and analysis tests. */
export const detectedJob: Job = {
  id: "job-go",
  url: "https://www.upwork.com/jobs/~0123456789",
  title: "Senior Python Backend Developer",
  description:
    "We are looking for an experienced backend engineer to build and scale our Django-based platform. You will own API design, database performance, and deployment. Some overlap with US working hours is expected for daily standups.",
  skills: ["Python", "Django", "PostgreSQL", "Docker", "AWS"],
  hourlyRateMin: 30,
  hourlyRateMax: 50,
  experienceLevel: "Intermediate",
  postedAgo: "Posted 2 hours ago",
}

/** GO analysis for the detected job. */
export const goAnalysis: FitAnalysis = {
  score: 82,
  status: "GO",
  label: "Strong match",
  summary:
    "Your core stack lines up closely with what the client needs, and the budget sits right at your preferred rate. Watch the cloud and communication requirements.",
  strengths: [
    "Strong Python and Django match",
    "PostgreSQL and Docker requirements match your profile",
    "Client budget matches your preferred hourly rate",
  ],
  risks: [
    "AWS experience is preferred but missing from your profile",
    "Client expects some US timezone overlap",
    "Spoken English may matter for client meetings",
  ],
  breakdown: {
    skills: 88,
    experience: 75,
    rate: 95,
    english: 60,
    requirements: 80,
  },
}
