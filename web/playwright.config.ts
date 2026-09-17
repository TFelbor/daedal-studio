import { defineConfig, devices } from '@playwright/test'

/**
 * The viewport smoke, and nothing else.
 *
 * This repository has no frontend test runner and this is not an attempt to add one:
 * the suite under `e2e/` asserts one thing — that four pages fit inside a phone — and
 * the reason it needs a browser is that no source assertion can answer it. Layout is
 * what the engine does with the rules, not what the rules say.
 *
 * It runs against the **production build**, served by `vite preview`, because that is
 * the artifact the server image ships. A dev server would type-check nothing and would
 * serve a different CSS pipeline than the one in `web/dist`.
 */
export default defineConfig({
  testDir: './e2e',
  // One browser, one worker. Every test here drives the same preview server and writes
  // into the same screenshot directory; parallelism buys a few seconds and costs a
  // class of flake nobody would enjoy diagnosing.
  workers: 1,
  fullyParallel: false,
  // A screenshot committed to the repository must not move because a runner was busy.
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],

  use: {
    baseURL: 'http://127.0.0.1:4173',
    ...devices['Desktop Chrome'],
    // Blocked deliberately. The worker is a *cache*, and a cache is the one thing that
    // makes a layout test lie: the second run would measure the first run's CSS.
    // `tests/test_pwa_shell.py` is what checks the worker itself.
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
  },

  webServer: {
    // `--host 127.0.0.1` is load-bearing: `vite preview` defaults to `localhost`, which
    // on a runner with IPv6 resolves to `::1` first, and Playwright polls the URL below
    // over IPv4 — so the server starts, serves nothing to the poller and the run dies
    // three minutes later saying it timed out waiting.
    command: 'npm run build && npm run preview -- --port 4173 --strictPort --host 127.0.0.1',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
