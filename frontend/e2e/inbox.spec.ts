import { test, expect } from "@playwright/test";
import { login } from "./helpers";

test.describe("Boîte de réception", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/conversations");
  });

  test("affiche la liste et les nouveaux filtres (priorité, tri, sélection)", async ({
    page,
  }) => {
    // Le tri par priorité/récence (#4).
    await expect(page.getByLabel("Trier les conversations")).toBeVisible();
    // Les filtres de priorité (#4).
    await expect(page.getByRole("button", { name: "Critique", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Haute", exact: true })).toBeVisible();
    // Le mode sélection multiple (#1).
    await expect(page.getByRole("button", { name: "Sélection" })).toBeVisible();
  });

  test("le filtre de priorité est cliquable et reste sur la page", async ({ page }) => {
    await page.getByRole("button", { name: "Critique", exact: true }).click();
    await expect(page).toHaveURL(/\/conversations/);
    // Le compteur de conversations reste rendu (la liste s'est rechargée).
    await expect(page.getByText(/conversation/i).first()).toBeVisible();
  });

  test("la cloche de notifications est présente dans la barre", async ({ page }) => {
    await expect(
      page.getByRole("button", { name: "Notifications", exact: true })
    ).toBeVisible();
  });
});
