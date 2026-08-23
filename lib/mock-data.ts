import type {
  FitAnalysis,
  FreelancerProfile,
  HistoryEntry,
  Job,
} from "./types"

export const defaultProfile: FreelancerProfile = {
  specialization: "Backend Developer",
  skills: ["Python", "Django", "FastAPI", "PostgreSQL", "Docker"],
  experienceYears: 5,
  preferredRate: 35,
  englishLevel: "Upper Intermediate",
}

/** The job currently detected on the Upwork tab. */
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

/** A NO-GO job used for previewing the weak-match state. */
export const noGoJob: Job = {
  id: "job-nogo",
  url: "https://www.upwork.com/jobs/~0987654321",
  title: "DevOps Engineer — AWS Infrastructure",
  description:
    "Seeking a senior DevOps engineer with deep AWS experience to manage large-scale infrastructure. Must have native-level English for daily client calls and full US timezone overlap.",
  skills: ["AWS", "Terraform", "Kubernetes", "CI/CD", "Python"],
  hourlyRateMin: 15,
  hourlyRateMax: 22,
  experienceLevel: "Expert",
  postedAgo: "Posted 5 hours ago",
}

export const noGoAnalysis: FitAnalysis = {
  score: 43,
  status: "NO_GO",
  label: "Weak match",
  summary:
    "There is some overlap in Python and backend fundamentals, but the role centers on skills you do not list, pays well below your rate, and demands native English.",
  strengths: [
    "Python matches your profile",
    "Backend experience is relevant to the role",
    "Infrastructure fundamentals may transfer to the project",
  ],
  risks: [
    "Requires 5+ years of dedicated AWS experience",
    "Budget is significantly below your preferred rate",
    "Native-level English is requested",
  ],
  breakdown: {
    skills: 45,
    experience: 55,
    rate: 25,
    english: 40,
    requirements: 38,
  },
}

export const historySeed: HistoryEntry[] = [
  {
    id: "h1",
    jobTitle: "Python Django Developer",
    score: 82,
    status: "GO",
    timestamp: "Today, 10:42",
    createdAt: "2026-08-23T10:42:00.000Z",
    analysis: goAnalysis,
    job: detectedJob,
  },
  {
    id: "h2",
    jobTitle: "DevOps Engineer — AWS",
    score: 43,
    status: "NO_GO",
    timestamp: "Yesterday",
    createdAt: "2026-08-22T10:42:00.000Z",
    analysis: noGoAnalysis,
    job: noGoJob,
  },
  {
    id: "h3",
    jobTitle: "Backend API Developer",
    score: 76,
    status: "GO",
    timestamp: "Aug 10",
    createdAt: "2026-08-10T10:42:00.000Z",
    analysis: {
      ...goAnalysis,
      score: 76,
      label: "Good match",
      summary:
        "Solid overlap on backend fundamentals and rate. A couple of preferred tools are missing but nothing blocking.",
      breakdown: { skills: 80, experience: 78, rate: 90, english: 62, requirements: 72 },
    },
    job: {
      id: "job-h3",
      url: "https://www.upwork.com/jobs/~0111111111",
      title: "Backend API Developer",
      description: "Build and maintain REST APIs for a growing SaaS product.",
      skills: ["Python", "FastAPI", "PostgreSQL", "Redis"],
      hourlyRateMin: 28,
      hourlyRateMax: 45,
      experienceLevel: "Intermediate",
      postedAgo: "Posted Aug 10",
    },
  },
]

export const loadingSteps = [
  "Reading job requirements",
  "Comparing skills",
  "Checking rate and experience",
  "Evaluating risks",
]

export const breakdownLabels: Record<keyof FitAnalysis["breakdown"], string> = {
  skills: "Skills",
  experience: "Experience",
  rate: "Rate",
  english: "English",
  requirements: "Requirements",
}
