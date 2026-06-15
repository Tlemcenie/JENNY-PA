import { expect, type Page } from "@playwright/test";

// Identifiants du compte de démonstration (seedé en base).
export const DEMO_EMAIL = "demo@jenny.ai";
export const DEMO_PASSWORD = "Demo!1234";

/** Connexion via l'UI réelle. Laisse l'app sur sa page post-login (/chat). */
export async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(DEMO_EMAIL);
  await page.locator('input[type="password"]').fill(DEMO_PASSWORD);
  await page.locator('button[type="submit"]').click();
  // Le login réussi redirige hors de /login (vers /chat).
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
}
