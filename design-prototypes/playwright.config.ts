import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: 'smoke.spec.ts',
  testIgnore: 'archive/**',
  timeout: 180_000,
  workers: 1,
  reporter: 'list',
  webServer: { command: 'pnpm dev', url: 'http://localhost:5178/workbench', reuseExistingServer: true, timeout: 60_000 },
  use: {
    baseURL: 'http://localhost:5178',
    channel: 'msedge',
    viewport: { width: 1280, height: 800 },
    launchOptions: { args: ['--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader'] },
  },
});
