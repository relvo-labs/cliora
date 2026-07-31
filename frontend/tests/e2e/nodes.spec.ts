import { expect, test } from "@playwright/test";

// Full authenticated flow (login → nodes → enrollment). It needs the whole
// stack: Central + PostgreSQL (migrated) + a seeded admin. It is skipped unless
// E2E_FULL_STACK=1 and the admin credentials are provided, so CI runs it only in
// the integration/e2e-matrix job that stands up that stack. See docs/p1-report.md.
const fullStack = process.env.E2E_FULL_STACK === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "";

test.describe("authenticated node control plane", () => {
  test.skip(
    !fullStack || !adminUser,
    "requires E2E_FULL_STACK + seeded admin credentials",
  );

  // The landing page is the dashboard (P4-08); the nodes list is one navigation
  // away. Both halves are asserted because the previous version expected login
  // to land on /nodes and had been failing since the dashboard shipped.
  test("admin signs in, lands on the dashboard, and reaches the nodes list", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.locator('input[name="username"]').fill(adminUser);
    await page.locator('input[name="password"]').fill(adminPass);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await page.goto("/nodes");
    await expect(page.getByRole("heading", { name: "Nodes" })).toBeVisible();
  });

  test("admin can open the enrollment page and generate a one-time token", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.locator('input[name="username"]').fill(adminUser);
    await page.locator('input[name="password"]').fill(adminPass);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await page.goto("/enrollment");
    await page.getByRole("button", { name: "Generate token" }).click();
    await expect(page.getByText("Token created")).toBeVisible();
    await expect(page.getByText(/curl -fsSL .*install-script/)).toBeVisible();
  });
});
