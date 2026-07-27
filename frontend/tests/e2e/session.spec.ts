import { expect, Page, test } from "@playwright/test";

// Full session → terminal flow (login → sessions → New Session → workspace →
// live terminal → reconnect → terminate). Like nodes.spec.ts this needs the
// whole stack — Central + PostgreSQL (migrated) + a seeded admin — and is
// skipped unless E2E_FULL_STACK=1 with admin credentials. The interactive
// parts additionally need an *online node* with a runtime; the CI e2e job
// stands one up with the Fake CLI (see scripts/e2e/run-stack.sh and
// .github/workflows/p2.yml). When no online node is present the interactive
// tests skip themselves rather than fail, so the suite stays green on a
// node-less stack while still asserting the list/permission surface.
const fullStack = process.env.E2E_FULL_STACK === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "";

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/nodes/);
}

function newSessionDialog(page: Page) {
  return page
    .getByRole("dialog")
    .filter({ has: page.getByRole("heading", { name: "New session" }) });
}

// Opens the New Session dialog and returns the online nodes it offers. The
// interactive tests use this to skip themselves when the stack has no node.
async function openDialogAndCountNodes(page: Page): Promise<number> {
  await page.goto("/sessions");
  await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
  await page.getByRole("button", { name: "New session" }).click();
  const dialog = newSessionDialog(page);
  await expect(dialog).toBeVisible();
  // The dialog fetches nodes asynchronously on open; wait for the first real
  // <option> (index 1, after the disabled placeholder) before counting so a
  // present-but-not-yet-loaded node is not mistaken for "no node".
  await dialog
    .locator("select")
    .first()
    .locator("option")
    .nth(1)
    .waitFor({ state: "attached", timeout: 8_000 })
    .catch(() => {});
  // Options minus the disabled "Select an online node…" placeholder.
  return dialog
    .locator("select")
    .first()
    .locator("option:not([disabled])")
    .count();
}

test.describe("session & terminal", () => {
  test.skip(
    !fullStack || !adminUser,
    "requires E2E_FULL_STACK + seeded admin credentials",
  );

  test("admin sees the sessions list and the create action", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/sessions");
    await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "New session" }),
    ).toBeVisible();
  });

  test("create → live terminal → reconnect → terminate", async ({ page }) => {
    await signIn(page);
    const nodeCount = await openDialogAndCountNodes(page);
    test.skip(nodeCount === 0, "no online node available in this stack");

    const dialog = newSessionDialog(page);
    // Node → runtime → workspace are dependent; selecting the node populates the
    // runtime list and pre-fills the first allowed workspace root.
    await dialog.locator("select").first().selectOption({ index: 1 });
    const runtime = dialog.locator("select").nth(1);
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    const workspace = dialog.locator('input[list="roots"]');
    await expect(workspace).not.toHaveValue("");
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("e2e-terminal");
    await dialog.getByRole("button", { name: "Start" }).click();

    // Landed on the workspace route as the writer.
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    await expect(
      page.getByRole("heading", { name: "e2e-terminal" }),
    ).toBeVisible();
    await expect(page.locator('[data-role="writer"]')).toBeVisible();

    const terminalHost = page.locator(
      '[aria-label="Interactive CLI terminal"]',
    );
    await expect(terminalHost).toBeVisible();
    // The Fake CLI prints this banner on launch; seeing it in the xterm DOM
    // proves the daemon → relay → ws → xterm pipeline is live end to end.
    await expect(page.locator(".xterm-rows")).toContainText("FAKECLI_READY", {
      timeout: 15_000,
    });
    await expect(page.locator('[data-status="connected"]')).toBeVisible();

    // Browser refresh must reattach without killing the session (ADR 0012).
    await page.reload();
    await expect(terminalHost).toBeVisible();
    await expect(page.locator(".xterm-rows")).toContainText("FAKECLI_READY", {
      timeout: 15_000,
    });
    await expect(page.locator('[data-status="connected"]')).toBeVisible();

    // Terminate: graceful → force → state update (running leaves for good).
    await page.getByRole("button", { name: "Terminate" }).click();
    const confirm = page.getByRole("dialog", { name: "Terminate session" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Terminate" }).click();
    await expect(
      page.locator('[data-status="terminated"], [data-status="exited"]'),
    ).toBeVisible({ timeout: 15_000 });
  });
});
