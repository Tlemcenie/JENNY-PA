import { defineConfig, devices } from "@playwright/test";

/**
 * Tests E2E front (#20). Vérifient les parcours clés réellement rendus par le
 * navigateur (connexion, inbox + nouvelles fonctionnalités). Réutilise le
 * serveur de dev s'il tourne déjà ; l'API doit être disponible sur :8000.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    port: 3000,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
