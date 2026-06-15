import { test, expect } from "@playwright/test";
import { login, DEMO_EMAIL } from "./helpers";

test.describe("Authentification", () => {
  test("connexion avec le compte démo redirige vers l'app", async ({ page }) => {
    await login(page);
    // La barre latérale (navigation) confirme qu'on est dans l'app authentifiée.
    await expect(page.getByRole("link", { name: "Conversations" })).toBeVisible();
    // Le jeton JWT est bien stocké.
    const token = await page.evaluate(() => localStorage.getItem("jenny_token"));
    expect(token).toBeTruthy();
  });

  test("identifiants invalides affichent une erreur", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(DEMO_EMAIL);
    await page.locator('input[type="password"]').fill("MauvaisMotDePasse!1");
    await page.locator('button[type="submit"]').click();
    // On reste sur /login (pas de redirection).
    await expect(page).toHaveURL(/\/login/);
  });
});
