import { defineConfig } from '@playwright/test'
import base from './playwright.config'

const servers = Array.isArray(base.webServer) ? base.webServer : [base.webServer!]

// Run with --headed: actual tab visibility, real components and metrics transport.
// Metrics stop at the browser transport boundary; no external collector or paid model.
export default defineConfig({
  ...base,
  testMatch: 'visibility.spec.ts',
  metadata: { realVisibility: true },
  webServer: servers.map(server => ({
    ...server,
    ...(server.url === 'http://127.0.0.1:38153' ? { env: {
      ...server.env,
      METRICS_COOKIE_SECRET: 'visibility-smoke-cookie-secret-32-characters',
      METRICS_BACKEND_URL: 'https://metrics.example.test',
      METRICS_BRIDGE_KEY: 'visibility-smoke-only',
      METRICS_ENVIRONMENT: 'test',
    } } : {}),
  })),
})
