import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./e2e", timeout: 60_000, workers: 1, fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:38153", trace: "retain-on-failure", locale: "en-US", actionTimeout: 10_000 },
  webServer: [
    { command: "backend/.venv/bin/python e2e/backend.py", url: "http://127.0.0.1:38154/health/live", reuseExistingServer: false, env: { PYTHONPATH: "backend/src" } },
    { command: "node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 38153", url: "http://127.0.0.1:38153", reuseExistingServer: false,
      env: { FITCHECK_BACKEND_URL: "http://127.0.0.1:38154", FITCHECK_WEBSITE_ORIGIN: "http://127.0.0.1:38153", METRICS_COOKIE_SECRET: "", METRICS_BACKEND_URL: "", METRICS_BRIDGE_KEY: "" } },
  ],
})
