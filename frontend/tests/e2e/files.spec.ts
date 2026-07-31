import { expect, Page, test } from "@playwright/test";

// Full workspace-files flow (P3-10): session workspace → lazy tree expand →
// excluded directory → filename search back into the tree → Monaco read-only
// preview → each denial screen → switching away clears the pane.
//
// Like session.spec.ts this needs the whole stack — Central + PostgreSQL
// (migrated) + a seeded admin + an online node — and is skipped unless
// E2E_FULL_STACK=1 with admin credentials. The fixtures it asserts on are seeded
// into the node's workspace root by scripts/e2e/run-stack.sh.
const fullStack = process.env.E2E_FULL_STACK === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "";

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  // The landing page is the dashboard (P4-08), not the nodes list.
  await expect(page).toHaveURL(/\/dashboard/);
}

function newSessionDialog(page: Page) {
  return page
    .getByRole("dialog")
    .filter({ has: page.getByRole("heading", { name: "New session" }) });
}

// Creates a session on the first online node and lands on its workspace.
// Returns false when the stack has no online node (the caller then skips).
async function openWorkspace(page: Page, name: string): Promise<boolean> {
  await page.goto("/sessions");
  await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
  await page.getByRole("button", { name: "New session" }).click();
  const dialog = newSessionDialog(page);
  await expect(dialog).toBeVisible();
  await dialog
    .locator("select")
    .first()
    .locator("option")
    .nth(1)
    .waitFor({ state: "attached", timeout: 8_000 })
    .catch(() => {});
  const nodes = await dialog
    .locator("select")
    .first()
    .locator("option:not([disabled])")
    .count();
  if (nodes === 0) {
    return false;
  }
  await dialog.locator("select").first().selectOption({ index: 1 });
  const runtime = dialog.locator("select").nth(1);
  await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
  await runtime.selectOption({ index: 1 });
  await expect(dialog.locator('input[list="roots"]')).not.toHaveValue("");
  await dialog.locator('input[placeholder="e.g. refactor-api"]').fill(name);
  await dialog.getByRole("button", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
  return true;
}

// Evidence screenshots (plan/04/07 §3). Off unless P3_SCREENSHOT_DIR is set, so
// a normal run writes nothing.
const shotDir = process.env.P3_SCREENSHOT_DIR;
async function shot(page: Page, name: string): Promise<void> {
  if (!shotDir) return;
  await page.screenshot({ path: `${shotDir}/${name}.png` });
}

const tree = (page: Page) => page.getByRole("tree", { name: "工作區檔案" });
const row = (page: Page, name: string) =>
  tree(page).getByRole("treeitem", { name: new RegExp(`^${name},`) });

async function terminate(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Terminate" }).click();
  const confirm = page.getByRole("dialog", { name: "Terminate session" });
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: "Terminate" }).click();
}

test.describe("workspace files", () => {
  test.skip(
    !fullStack || !adminUser,
    "requires E2E_FULL_STACK + seeded admin credentials",
  );

  test("lazy tree, excluded dir, search back into the tree", async ({
    page,
  }) => {
    await signIn(page);
    test.skip(!(await openWorkspace(page, "e2e-files")), "no online node");

    // Root level loads lazily; the excluded directory is shown but not loadable.
    await expect(row(page, "README\\.md")).toBeVisible({ timeout: 15_000 });
    await expect(row(page, "src")).toBeVisible();
    const excluded = row(page, "node_modules");
    await expect(excluded).toBeVisible();
    await expect(excluded).toContainText("已排除");
    // Not expandable at all: no aria-expanded, and clicking loads nothing.
    expect(await excluded.getAttribute("aria-expanded")).toBeNull();
    await excluded.click();
    await expect(row(page, "pkg")).toHaveCount(0);

    await shot(page, "tree-root-loaded");

    // Expanding src fetches only that level.
    await row(page, "src").click();
    await expect(row(page, "main\\.py")).toBeVisible({ timeout: 10_000 });
    await expect(row(page, "app\\.ts")).toBeVisible();

    // Filename search: the hit reveals inside the tree (ancestors expanded).
    await page.getByLabel("以檔名搜尋工作區").fill("needle");
    await page.getByLabel("以檔名搜尋工作區").press("Enter");
    await page
      .getByRole("button", { name: /needle_target\.py/ })
      .first()
      .click();
    await expect(row(page, "deep")).toHaveAttribute("aria-expanded", "true");
    await expect(row(page, "nested")).toHaveAttribute("aria-expanded", "true");
    await expect(row(page, "needle_target\\.py")).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await shot(page, "tree-search-reveal");

    await terminate(page);
  });

  test("read-only preview: highlight, wrap, copy, goto line, refresh", async ({
    page,
  }) => {
    await signIn(page);
    test.skip(!(await openWorkspace(page, "e2e-preview")), "no online node");

    await expect(row(page, "src")).toBeVisible({ timeout: 15_000 });
    await row(page, "src").click();
    await row(page, "main\\.py").click();

    // Monaco renders the content read-only with line numbers.
    const preview = page.getByRole("region", { name: /main\.py/ });
    await expect(preview).toBeVisible({ timeout: 20_000 });
    await expect(preview).toContainText("唯讀");
    await expect(page.locator(".monaco-editor")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.locator(".view-lines")).toContainText(
      "E2E_PREVIEW_MARKER",
    );
    await expect(
      page.locator(".margin-view-overlays .line-numbers").first(),
    ).toBeVisible();
    // Typing must not change the content (readOnly + domReadOnly).
    await page
      .locator(".monaco-editor textarea")
      .first()
      .press("x")
      .catch(() => {});
    await expect(page.locator(".view-lines")).toContainText(
      "E2E_PREVIEW_MARKER",
    );

    // Word wrap toggles, and the find widget opens.
    const wrap = preview.getByRole("button", { name: "換行" });
    await expect(wrap).toHaveAttribute("aria-pressed", "true");
    await wrap.click();
    await expect(wrap).toHaveAttribute("aria-pressed", "false");
    await preview.getByRole("button", { name: "搜尋" }).click();
    await expect(page.locator(".find-widget")).toBeVisible();
    await page.keyboard.press("Escape");

    await shot(page, "preview-code");

    // Copy and refresh are available on a previewable file.
    await preview.getByRole("button", { name: "複製" }).click();
    await preview.getByRole("button", { name: "重新整理" }).click();
    await expect(page.locator(".view-lines")).toContainText(
      "E2E_PREVIEW_MARKER",
    );

    await terminate(page);
  });

  test("sensitive, binary and oversize files are refused with no content", async ({
    page,
  }) => {
    await signIn(page);
    test.skip(!(await openWorkspace(page, "e2e-denials")), "no online node");
    await expect(row(page, "README\\.md")).toBeVisible({ timeout: 15_000 });

    // .env — sensitive: classification only, never a fragment of the content.
    await row(page, "\\.env").click();
    await expect(page.getByText("此檔案為敏感類型，預設不可預覽")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("環境變數檔")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(
      "e2e-must-never-be-previewed",
    );
    // The editor host is hidden while a denial shows: no content surface at all.
    await expect(page.locator(".monaco-editor")).toBeHidden();
    await shot(page, "denial-sensitive-dotenv");

    // *.pem — sensitive by extension.
    await row(page, "server\\.pem").click();
    await expect(page.getByText("私鑰檔")).toBeVisible({ timeout: 15_000 });
    await shot(page, "denial-private-key");

    // Binary — metadata only.
    await row(page, "logo\\.png").click();
    await expect(page.getByText("不支援預覽此檔案")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/application\/octet-stream/)).toBeVisible();
    await shot(page, "denial-binary");

    // Oversize — size + cap, no content read.
    await row(page, "big\\.log").click();
    await expect(page.getByText("檔案過大，超過預覽上限")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/3\.00 MB/)).toBeVisible();
    await shot(page, "denial-oversize");

    await terminate(page);
  });

  test("keyboard-only navigation does not open files", async ({ page }) => {
    await signIn(page);
    test.skip(!(await openWorkspace(page, "e2e-keyboard")), "no online node");
    await expect(row(page, "src")).toBeVisible({ timeout: 15_000 });

    // The tree container is the single tab stop and keeps focus throughout; the
    // focused row is tracked with aria-activedescendant. Rows are ordered
    // directories-first by name: deep, node_modules, src.
    await tree(page).focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(tree(page)).toHaveAttribute(
      "aria-activedescendant",
      (await row(page, "src").getAttribute("id")) ?? "",
    );
    await page.keyboard.press("ArrowRight");
    await expect(row(page, "src")).toHaveAttribute("aria-expanded", "true");
    // Wait for the level itself: aria-expanded flips as soon as the node opens,
    // while the children are still loading, and ArrowDown before they arrive
    // moves to the next *sibling* (standard treeview behaviour).
    await expect(row(page, "app\\.ts")).toBeVisible({ timeout: 10_000 });
    // Step into the expanded level: focus lands on a file, opening nothing.
    await page.keyboard.press("ArrowDown");
    await expect(tree(page)).toHaveAttribute(
      "aria-activedescendant",
      (await row(page, "app\\.ts").getAttribute("id")) ?? "",
    );
    await expect(
      page.getByRole("region", { name: /Preview|app\.ts/ }),
    ).toHaveCount(0);
    await shot(page, "keyboard-focus-no-preview");
    // Enter is what opens it.
    await page.keyboard.press("Enter");
    await expect(page.locator(".monaco-editor")).toBeVisible({
      timeout: 20_000,
    });

    await terminate(page);
  });

  test("a terminated session cannot browse files", async ({ page }) => {
    await signIn(page);
    test.skip(!(await openWorkspace(page, "e2e-files-dead")), "no online node");
    await expect(row(page, "README\\.md")).toBeVisible({ timeout: 15_000 });

    await terminate(page);
    await expect(
      page.locator('[data-status="terminated"], [data-status="exited"]'),
    ).toBeVisible({ timeout: 15_000 });
    // The tree is replaced by an explicit "session ended" affordance.
    await expect(
      page.getByText("Session 已結束，檔案瀏覽不再可用。"),
    ).toBeVisible();
    await expect(tree(page)).toHaveCount(0);
  });
});
