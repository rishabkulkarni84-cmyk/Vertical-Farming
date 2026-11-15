import { defineConfig } from '@playwright/test'

// Uses an isolated backend (port 8001, throwaway SQLite DB) and Vite (port 5174).
// Set PLAYWRIGHT_CHROME_PATH to use a system Chrome when Playwright's browser download is unavailable.
const chrome = process.env.PLAYWRIGHT_CHROME_PATH

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    launchOptions: chrome ? { executablePath: chrome, args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] } : { args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] },
  },
  webServer: [
    {
      command: 'rm -f /tmp/verdant-e2e.db* && rm -rf /tmp/verdant-e2e-storage && cd ../backend && DATABASE_URL=sqlite:////tmp/verdant-e2e.db STORAGE_DIR=/tmp/verdant-e2e-storage ENVIRONMENT=test python3 -m uvicorn app.main:app --port 8001',
      url: 'http://127.0.0.1:8001/api/health',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'VITE_API_PROXY=http://127.0.0.1:8001 npx vite --port 5174 --strictPort',
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
