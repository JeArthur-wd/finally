import { defineConfig, devices } from '@playwright/test';

/**
 * FinAlly E2E config. Tests run on the host against a running container.
 * BASE_URL overrides the target (default: the e2e container on :8001).
 */
const baseURL = process.env.BASE_URL ?? 'http://localhost:8001';

export default defineConfig({
  testDir: './e2e',
  // All tests share one backend user ("default") and call POST /api/reset,
  // so they must run serially.
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    viewport: { width: 1600, height: 1000 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } } }],
});
