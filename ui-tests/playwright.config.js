import { defineConfig, devices } from "@playwright/test";

// The stack must be running: `cd deploy/compose && docker compose up -d`.
// Base URL is Caddy's published HTTPS port. Caddy uses a local CA that
// isn't in the system trust store, so `ignoreHTTPSErrors` is required.
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false, // shared Postgres — keep serial to avoid cross-test bleed
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "https://localhost:8443",
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
