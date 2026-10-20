import { WebsiteApp } from "@/components/web/website-app"
import { connection } from "next/server"

export default async function Page() {
  await connection()
  // Public campaign codes mirror backend FITCHECK_METRICS_CAMPAIGN_CODES (JSON list).
  const knownCampaignCodes = (process.env.METRICS_CAMPAIGN_CODES ?? "").split(",").map(code => code.trim()).filter(code => /^[a-z][a-z0-9_]{0,79}$/.test(code)).slice(0, 100)
  const metricsEnabled = Boolean(process.env.METRICS_COOKIE_SECRET && process.env.METRICS_BACKEND_URL && process.env.METRICS_BRIDGE_KEY)
  return <WebsiteApp metricsEnabled={metricsEnabled} knownCampaignCodes={knownCampaignCodes} />
}
