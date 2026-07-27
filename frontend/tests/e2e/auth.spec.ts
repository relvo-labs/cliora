import { expect, test } from "@playwright/test";

// These specs exercise the client-side auth gate and Login page. They need only
// the frontend dev server (no backend), so they run in the standard e2e job.
test.describe("auth guard", () => {
  test("unauthenticated visit to a protected route redirects to login", async ({
    page,
  }) => {
    await page.goto("/nodes");
    await expect(page).toHaveURL(/\/login\?redirect=(?:%2F|\/)nodes/);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("login field is focused for keyboard entry", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator('input[name="username"]')).toBeFocused();
  });

  test("a failed sign-in shows a generic, account-agnostic error", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.locator('input[name="username"]').fill("someone");
    await page.locator('input[name="password"]').fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toContainText(
      /sign in|username or password/i,
    );
  });
});
