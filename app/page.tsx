import { WebsiteApp } from "@/components/web/website-app"
import { connection } from "next/server"
import { bridgeReadiness } from "@/lib/metrics/bridge"
import type { MetricsEnvironment } from "@/lib/metrics/types"

export default async function Page() {
  await connection()
  // Public campaign codes mirror backend FITCHECK_METRICS_CAMPAIGN_CODES (JSON list).
  const knownCampaignCodes = (process.env.METRICS_CAMPAIGN_CODES ?? "").split(",").map(code => code.trim()).filter(code => /^[a-z][a-z0-9_]{0,79}$/.test(code)).slice(0, 100)
  const metricsEnabled = Boolean(process.env.METRICS_COOKIE_SECRET && bridgeReadiness({
    backendUrl: process.env.METRICS_BACKEND_URL,
    bridgeKey: process.env.METRICS_BRIDGE_KEY,
    environment: process.env.METRICS_ENVIRONMENT as MetricsEnvironment | undefined,
    runtime: process.env.NODE_ENV,
    allowLocalHttp: process.env.METRICS_ALLOW_LOCAL_HTTP === 'true',
  }).configured)
  return <WebsiteApp metricsEnabled={metricsEnabled} knownCampaignCodes={knownCampaignCodes} />
}
