import { defineConfig, devices } from "@playwright/test";

// Browser-grade qualification for DB-2.7 (RES-380).
//
// One Chromium project, one worker, and no persisted diagnostics: traces, screenshots, videos
// and HAR files would capture a page holding a live session credential, and none of them is
// evidence this gate needs. The assertions are the evidence. The output is the console
// reporter and, when CI asks for it, Playwright's JSON reporter.
//
// `webServer` serves `vite.e2e.config.ts`, whose root is `e2e/app` and whose entry imports the
// production router, provider, shell and route tree. The production `index.html` and
// `src/main.tsx` are untouched by this configuration.
const port = Number(process.env.DYNAMISBENCH_E2E_PORT ?? 5173);

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  forbidOnly: true,
  retries: 0,
  reporter: process.env.DYNAMISBENCH_E2E_JSON === undefined
    ? [["list"]]
    : [["list"], ["json", { outputFile: process.env.DYNAMISBENCH_E2E_JSON }]],

  use: {
    baseURL: `http://localhost:${port}`,
    trace: "off",
    screenshot: "off",
    video: "off",
    serviceWorkers: "block",
    // The real sidecar's development origin is exactly http://localhost:5173. A request from
    // any other spelling of loopback would be refused by the API, which is the CORS boundary
    // this gate wants to exercise rather than work around.
    ignoreHTTPSErrors: false,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: `pnpm exec vite --config vite.e2e.config.ts --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
