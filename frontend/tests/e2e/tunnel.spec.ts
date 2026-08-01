import { expect, Page, test } from "@playwright/test";

// Port forwarding, end to end (plan/11 PG-11 §2.3): enable the integration as an
// administrator, forward a port on a real node, see the URL the provider assigned, close it.
//
// The provider is a stand-in (`scripts/e2e/run-stack.sh` starts the daemon with
// `faketunnelprovider`), so this exercises Central, the protocol, the supervisor and both
// pages without an account, without outbound network, and without a CI whose red means
// "somebody else had an outage".
//
// **The URL is never opened.** The fake announces a hostname under `.example.invalid`, which
// RFC 2606 guarantees cannot resolve; what this suite asserts is that the link is *presented*
// correctly — new window, `rel="noopener noreferrer"` — which is the whole of the platform's
// contract with the user here (ADR 0022 D6). A test that navigated to it would be asserting
// the provider's behaviour, not ours.
const fullStack = process.env.E2E_FULL_STACK === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "";
// The port `faketunnelapp` listens on. Must match the stack; the default mirrors it.
const appPort = Number(process.env.E2E_TUNNEL_APP_PORT ?? "5199");

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

// Enables the integration through the UI rather than through the API, because the
// acknowledgement gate is part of what this is testing: the server refuses `enabled: true`
// without it, and the page is where somebody reads what they are agreeing to.
async function enableIntegration(page: Page): Promise<void> {
  await page.goto("/settings/integrations");
  await expect(page.getByRole("heading", { name: "整合設定" })).toBeVisible();

  const enable = page.getByRole("button", { name: "啟用埠轉發" });
  const disable = page.getByRole("button", { name: "停用埠轉發" });
  if (await disable.isVisible().catch(() => false)) {
    return; // already on from an earlier run against the same database
  }
  // The four statements, and the checkbox that has to be ticked before the button works.
  await expect(
    page.getByText("服務商可以看到未加密的 HTTP 內容"),
  ).toBeVisible();
  await expect(enable).toBeDisabled();
  await page.locator('input[type="checkbox"]').first().check();
  await expect(enable).toBeEnabled();
  await enable.click();
  await expect(disable).toBeVisible();
}

// The stack's node id, from the nodes list. Returns "" when the stack has no online node,
// which is how the interactive cases skip themselves instead of failing.
async function onlineNodeId(page: Page): Promise<string> {
  const response = await page.request.get("/api/nodes");
  if (!response.ok()) {
    return "";
  }
  const nodes = (await response.json()) as { id: string; status: string }[];
  return nodes.find((node) => node.status === "online")?.id ?? "";
}

test.describe("port forwarding", () => {
  test.skip(
    !fullStack || !adminUser || !adminPass,
    "needs the full stack: E2E_FULL_STACK=1 with admin credentials (scripts/e2e/run-stack.sh)",
  );

  test("an administrator enables the integration and sees only a fingerprint", async ({
    page,
  }) => {
    await signIn(page);
    await enableIntegration(page);

    // Storing a credential must never echo it back — asserted against the whole rendered
    // page, not against a field, because a leak would be somewhere nobody added a field.
    const token = "E2EFAKETOKEN1234";
    await page.locator('input[type="password"]').fill(token);
    await page.getByRole("button", { name: "儲存憑證" }).click();
    await expect(page.getByText("憑證已儲存")).toBeVisible();
    expect(await page.content()).not.toContain(token);
    expect(await page.content()).not.toContain(token.slice(0, 6));
    await expect(page.getByText("已設定")).toBeVisible();

    // Clean up so a second run starts from the same place.
    await page.getByRole("button", { name: "清除憑證" }).click();
    await expect(page.getByText("憑證已清除")).toBeVisible();
  });

  test("forwards a port, shows the assigned URL, then closes it", async ({
    page,
  }) => {
    await signIn(page);
    await enableIntegration(page);
    const nodeId = await onlineNodeId(page);
    test.skip(nodeId === "", "the stack has no online node");

    await page.goto(`/nodes/${nodeId}/tunnels`);
    await expect(page.getByRole("heading", { name: "埠轉發" })).toBeVisible();

    // The prerequisites the node reported. All four must be met, or creating is refused
    // before any frame is sent — which is the behaviour, but not what this case is about.
    const prerequisites = page.locator("ul.prereq li");
    await expect(prerequisites).toHaveCount(4);
    await expect(page.locator("ul.prereq")).not.toContainText("✕");

    await page.getByRole("button", { name: "建立隧道" }).click();
    const form = page.locator("form.create");
    await form.locator('input[type="number"]').first().fill(String(appPort));
    // `public`: the fake provider enforces no basic auth, and this case is about the URL
    // being shown, so the weaker mode keeps the assertion about one thing. It costs an extra
    // confirmation, which is itself part of the contract (each public tunnel is confirmed).
    await form.locator("select").selectOption("public");
    await page.getByText("我了解並確認要建立不保護的隧道").click();
    // First tunnel on this node for this user: the server asks for the third-party
    // acknowledgement with a 422, and the form grows the four statements.
    await form.getByRole("button", { name: "建立" }).click();
    const firstTime = page.getByText("這是你在這台節點上的第一條隧道");
    if (await firstTime.isVisible().catch(() => false)) {
      await page.getByText("我了解並同意上述內容").click();
      await form.getByRole("button", { name: "建立" }).click();
    }

    // The one-time dialog, then the row.
    const dialog = page.getByRole("dialog", { name: "隧道已建立" });
    await expect(dialog).toBeVisible();
    const url = await dialog.getByRole("link").getAttribute("href");
    expect(url).toMatch(/^https:\/\/[a-z0-9-]+\.tunnel\.example\.invalid$/);
    await dialog.getByRole("button", { name: "關閉" }).click();

    const row = page.locator("table tbody tr").first();
    await expect(row).toContainText(String(appPort));
    await expect(row).toContainText("執行中");
    // D6: a new window is the only presentation, and `noopener` keeps the opened page from
    // reaching back into the console tab through `window.opener`.
    const link = row.getByRole("link", { name: /example\.invalid/ });
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    // The provider owns the URL and may reassign it; the page says so rather than letting
    // somebody paste it into a ticket believing otherwise.
    await expect(page.getByText("網址由服務商指派，可能變更")).toBeVisible();

    // Closing removes it from the live list. The confirmation says what the platform cannot
    // promise: the provider decides when the URL stops answering.
    await row.getByRole("button", { name: "關閉" }).click();
    await expect(page.getByText("網址的有效性由服務商決定")).toBeVisible();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "關閉" })
      .click();
    await expect(page.getByText("這台節點目前沒有隧道")).toBeVisible();
  });

  test("the rail offers integration settings to an administrator", async ({
    page,
  }) => {
    // Only the Admin half is checkable here: the stack seeds one account, and it is an
    // administrator. The negative — a Developer is offered nothing and is refused if they
    // type the URL — is asserted by `AppLayout.test.ts` and by the API's authorization tests,
    // which is the right place for it: hiding the entry is a courtesy, the 403 is the control.
    await signIn(page);
    await expect(page.getByRole("navigation")).toContainText("Integrations");
  });
});
