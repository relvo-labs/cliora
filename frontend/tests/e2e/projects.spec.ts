import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// The V2.0 project layer end to end (plan/16 06-…md §2.5).
//
// Skipped unless the stack is up *and* the project layer is switched on, because
// every route here answers 404 otherwise — which is the behaviour the flag-off
// suite asserts, and asserting both from one spec would mean one of them was
// always wrong.
//
//   CLIORA_PROJECTS_ENABLED=true E2E_PROJECTS=1 scripts/e2e/run-stack.sh \
//     bash -c 'cd frontend && npx playwright test projects.spec.ts'
//
// The two-node assertions additionally need E2E_SECOND_NODE=1, which brings up a
// second agentd with its own workspace root. They are skipped rather than faked
// when it is absent: "one project spans two machines" proven against one machine
// is not proven.
const enabled = process.env.E2E_PROJECTS === "1";
const twoNodes = process.env.E2E_SECOND_NODE === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "e2e-admin";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw";
const viewerUser = "e2e-viewer";
const viewerPass = process.env.E2E_SEED_PASSWORD ?? "e2e-seed-pw";
const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

async function signIn(
  page: Page,
  user: string,
  password: string,
): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/(dashboard|nodes|sessions)/);
}

async function tokenFor(
  request: APIRequestContext,
  username: string,
  password: string,
): Promise<string> {
  const resp = await request.post(`${API}/api/auth/login`, {
    data: { username, password },
  });
  return (await resp.json()).tokens.access_token;
}

async function adminToken(request: APIRequestContext): Promise<string> {
  return tokenFor(request, adminUser, adminPass);
}

function setRootEnabled(nodeId: string, path: string, enabled: boolean): void {
  execFileSync(
    "uv",
    [
      "run",
      "--project",
      "backend",
      "python",
      "scripts/pj/set-root-enabled.py",
      nodeId,
      path,
      enabled ? "on" : "off",
    ],
    { cwd: REPO, env: process.env, stdio: "inherit" },
  );
}

async function nodesWithRoots(request: APIRequestContext, token: string) {
  const list = await (
    await request.get(`${API}/api/nodes`, {
      headers: { authorization: `Bearer ${token}` },
    })
  ).json();
  const detailed = [];
  for (const node of list) {
    const detail = await (
      await request.get(`${API}/api/nodes/${node.id}`, {
        headers: { authorization: `Bearer ${token}` },
      })
    ).json();
    const root = (detail.workspace_roots ?? []).find(
      (r: { is_enabled: boolean }) => r.is_enabled,
    );
    if (detail.status === "online" && root) {
      detailed.push({ id: node.id, name: node.name, root: root.path });
    }
  }
  return detailed;
}

test.describe("V2.0 project layer", () => {
  test.skip(
    !enabled,
    "requires E2E_PROJECTS=1 and CLIORA_PROJECTS_ENABLED=true",
  );

  test("an Admin creates a project, binds a workspace, and sees it on the timeline", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request);
    const [node] = await nodesWithRoots(request, token);
    const slug = `e2e-${Date.now().toString(36)}`;

    await signIn(page, adminUser, adminPass);

    // The rail regains its Projects entry only when the layer is on.
    await expect(page.locator("nav a[href='/projects']")).toBeVisible();
    await expect(page.locator("nav [data-nav-group]")).toHaveText(
      "Infrastructure",
    );

    await page.goto("/projects");
    await page.getByRole("button", { name: "New project" }).click();
    await page.getByRole("textbox", { name: "Name", exact: true }).fill(slug);
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/);

    const projectId = page.url().split("/").pop()!;
    await page.getByRole("button", { name: "Bind workspace" }).click();
    const dialog = page.getByRole("dialog", { name: "Bind workspace" });
    await dialog.locator("select").selectOption(node.id);
    const path = dialog.locator('input[placeholder^="/path"]');
    await expect(path).toHaveValue(node.root);
    await dialog.getByRole("button", { name: "Bind", exact: true }).click();
    await expect(dialog).toBeHidden();
    // Scoped to the binding list: the same path also appears in the timeline row
    // for `workspace.bound`, which is correct but makes a page-wide locator
    // ambiguous.
    await expect(page.locator(".bindings li .path")).toHaveText(node.root);
    await expect(page.locator(".bindings li .node")).toHaveText(node.name);

    await page.getByRole("button", { name: "Activity" }).click();
    await expect(page.getByText("綁定 Workspace")).toBeVisible();
    // The label, not the wire value: a raw `workspace.bound` here means the view
    // is reading the audit vocabulary, whose keys are a disjoint set.
    await expect(page.getByText("workspace.bound")).toHaveCount(0);
  });

  test("a project session reaches the timeline and survives an unbind", async ({
    page,
    request,
  }) => {
    // The regression this guards: the button pushed a query string that nothing
    // read, so it navigated to an empty session list and looked broken.
    const token = await adminToken(request);
    const [node] = await nodesWithRoots(request, token);
    const created = await (
      await request.post(`${API}/api/projects`, {
        headers: { authorization: `Bearer ${token}` },
        data: { name: `prefill-${Date.now().toString(36)}` },
      })
    ).json();
    await request.post(`${API}/api/projects/${created.id}/workspaces`, {
      headers: { authorization: `Bearer ${token}` },
      data: { node_id: node.id, path: node.root },
    });

    await signIn(page, adminUser, adminPass);
    await page.goto(`/projects/${created.id}`);
    await page.getByRole("button", { name: "Open session" }).first().click();

    await expect(page).toHaveURL(/\/sessions\?/);
    const dialog = page.locator('div[role="dialog"]');
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByTestId("project-field").locator("select"),
    ).toHaveValue(created.id);
    await expect(
      dialog.getByTestId("project-field").locator("select"),
    ).toBeDisabled();
    await expect(dialog.locator('input[list="roots"]')).toHaveValue(node.root);

    const runtime = dialog
      .locator("label")
      .filter({ hasText: "Runtime" })
      .locator("select");
    await expect(runtime.locator("option:not([disabled])")).not.toHaveCount(0);
    await runtime.selectOption({ index: 1 });
    await dialog
      .locator('input[placeholder="e.g. refactor-api"]')
      .fill("project-live");
    await dialog.getByRole("button", { name: "Start" }).click();
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
    const sessionUrl = page.url();
    const sessionId = sessionUrl.split("/").pop()!;
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      {
        timeout: 15_000,
      },
    );

    await expect
      .poll(async () => {
        const activity = await (
          await request.get(`${API}/api/projects/${created.id}/activity`, {
            headers: { authorization: `Bearer ${token}` },
          })
        ).json();
        return activity.items.filter(
          (item: { kind: string }) => item.kind === "session.started",
        ).length;
      })
      .toBe(1);

    const adHoc = await request.post(`${API}/api/sessions`, {
      headers: { authorization: `Bearer ${token}` },
      data: {
        node_id: node.id,
        runtime: "claude",
        name: "ad-hoc-live",
        workspace: node.root,
        rows: 24,
        columns: 80,
      },
    });
    expect(adHoc.status()).toBe(201);
    const activityAfterAdHoc = await (
      await request.get(`${API}/api/projects/${created.id}/activity`, {
        headers: { authorization: `Bearer ${token}` },
      })
    ).json();
    expect(
      activityAfterAdHoc.items.filter(
        (item: { kind: string }) => item.kind === "session.started",
      ),
    ).toHaveLength(1);

    await page.goto(`/projects/${created.id}`);
    await page.getByRole("button", { name: "Unbind" }).click();
    await expect(page.locator(".bindings li")).toHaveCount(0);

    await page.goto(sessionUrl);
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "FAKECLI_READY",
      {
        timeout: 15_000,
      },
    );
    await expect(page.getByRole("tree", { name: "工作區檔案" })).toBeVisible();
    await page.locator("#panel-cli .xterm-rows").click();
    await page.keyboard.type("after-unbind\n");
    await expect(page.locator("#panel-cli .xterm-rows")).toContainText(
      "after-unbind",
    );
    const stillRunning = await request.get(`${API}/api/sessions/${sessionId}`, {
      headers: { authorization: `Bearer ${token}` },
    });
    expect((await stillRunning.json()).status).toBe("running");
  });

  test("a Viewer reads the project but is told why the actors are missing", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request);
    const created = await (
      await request.post(`${API}/api/projects`, {
        headers: { authorization: `Bearer ${token}` },
        data: { name: `viewer-${Date.now().toString(36)}` },
      })
    ).json();

    await signIn(page, viewerUser, viewerPass);
    await page.goto(`/projects/${created.id}`);
    await expect(
      page.getByRole("heading", { name: created.name }),
    ).toBeVisible();
    // Management is hidden for a role the server would refuse anyway.
    await expect(page.getByRole("button", { name: "Archive" })).toHaveCount(0);

    await page.getByRole("button", { name: "Activity" }).click();
    await expect(page.getByText("audit permission")).toBeVisible();
    // Stated, never a bare blank: silence would read as "nobody did this".
    const actors = page.locator(".timeline li .who");
    await expect(actors.first()).toHaveText("—");

    const viewerToken = await tokenFor(request, viewerUser, viewerPass);
    const refused = await request.post(`${API}/api/projects`, {
      headers: { authorization: `Bearer ${viewerToken}` },
      data: { name: "forged-from-viewer" },
    });
    expect(refused.status()).toBe(403);
    await expect
      .poll(async () => {
        const audit = await (
          await request.get(`${API}/api/audit`, {
            headers: { authorization: `Bearer ${token}` },
            params: { action: "authz.denied", limit: 50 },
          })
        ).json();
        return audit.items.some(
          (item: { metadata: { denied_action?: string; path?: string } }) =>
            item.metadata.denied_action === "project.manage" &&
            item.metadata.path === "/api/projects",
        );
      })
      .toBe(true);
  });

  test("a withdrawn root is shown distinctly and refused on use", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request);
    const [node] = await nodesWithRoots(request, token);
    const created = await (
      await request.post(`${API}/api/projects`, {
        headers: { authorization: `Bearer ${token}` },
        data: { name: `withdraw-${Date.now().toString(36)}` },
      })
    ).json();
    await request.post(`${API}/api/projects/${created.id}/workspaces`, {
      headers: { authorization: `Bearer ${token}` },
      data: { node_id: node.id, path: node.root },
    });

    setRootEnabled(node.id, node.root, false);
    try {
      await signIn(page, adminUser, adminPass);
      await page.goto(`/projects/${created.id}`);
      await expect(
        page.getByText("This machine no longer allows this directory"),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Open session" }),
      ).toBeDisabled();

      const refused = await request.post(`${API}/api/sessions`, {
        headers: { authorization: `Bearer ${token}` },
        data: {
          node_id: node.id,
          runtime: "claude",
          name: "must-not-start",
          workspace: node.root,
          project_id: created.id,
        },
      });
      expect(refused.status()).toBe(400);
      expect((await refused.json()).error.code).toBe(
        "WORKSPACE_OUTSIDE_ALLOWED_ROOT",
      );
    } finally {
      setRootEnabled(node.id, node.root, true);
    }
  });

  test("one project spans two nodes, each binding judged on its own machine", async ({
    page,
    request,
  }) => {
    test.skip(
      !twoNodes,
      "requires E2E_SECOND_NODE=1 (a second agentd, own root)",
    );

    const token = await adminToken(request);
    const nodes = await nodesWithRoots(request, token);
    expect(
      nodes.length,
      "the stack should expose two nodes with enabled roots",
    ).toBeGreaterThan(1);

    const created = await (
      await request.post(`${API}/api/projects`, {
        headers: { authorization: `Bearer ${token}` },
        data: { name: `span-${Date.now().toString(36)}` },
      })
    ).json();
    for (const node of nodes.slice(0, 2)) {
      await request.post(`${API}/api/projects/${created.id}/workspaces`, {
        headers: { authorization: `Bearer ${token}` },
        data: { node_id: node.id, path: node.root },
      });
    }

    await signIn(page, adminUser, adminPass);
    await page.goto(`/projects/${created.id}`);
    await expect(page.locator(".bindings li")).toHaveCount(2);
    for (const node of nodes.slice(0, 2)) {
      await expect(
        page.getByText(node.name, { exact: false }).first(),
      ).toBeVisible();
    }

    await page.goto("/projects");
    // Scoped to this project's row: the list holds every project the earlier tests
    // created, so a page-wide match would be both ambiguous and order-dependent.
    // The two roots sit on different machines, so the summary has to count
    // machines as well as directories.
    const row = page.locator("tbody tr").filter({ hasText: created.slug });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("2 directories");
    await expect(row).toContainText("2 nodes");
  });
});
