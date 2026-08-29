import { expect, test } from "@playwright/test";

const project = process.env.E2E_PROVIDER_PROJECT ?? "";
const task = process.env.E2E_PROVIDER_TASK ?? "";
const title = process.env.E2E_PROVIDER_TITLE ?? "";
const user = process.env.E2E_ADMIN_USER ?? "e2e-admin";
const password = process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw";

test("J17/J18 — merged PR reaches Drawer and revoked token reason is visible", async ({
  page,
}) => {
  test.skip(!project || !task || !title, "provider journey ids are required");

  await page.goto("/login");
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator('nav[aria-label="Primary"]')).toBeVisible();

  await page.goto(`/projects/${project}/work?task=${task}`);
  await expect(page.locator("[data-task-drawer]")).toBeVisible();
  const related = page.locator("[data-task-drawer]").getByRole("heading", {
    name: /這張卡的專案記憶/,
  });
  await expect(related).toBeVisible();
  await expect(page.locator("[data-task-drawer]")).toContainText(title);

  await page.goto(`/projects/${project}/overview`);
  await expect(page.getByText(/連續三次讀取失敗/)).toBeVisible();
  await expect(page.getByText(/Bad credentials/)).toBeVisible();
});
