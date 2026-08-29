import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// V2.1's browser proof. It deliberately uses the real HTTP API to arrange the
// less interesting data and the console for the decisions a person has to see:
// roadmap classification, optimistic-lock rollback, dependency refusal, and
// partial proposal acceptance.
const enabled = process.env.E2E_TASKS === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "e2e-admin";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw";
const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/(dashboard|nodes|sessions)/);
}

async function tokenFor(request: APIRequestContext): Promise<string> {
  const response = await request.post(`${API}/api/auth/login`, {
    data: { username: adminUser, password: adminPass },
  });
  expect(response.ok()).toBe(true);
  return (await response.json()).tokens.access_token;
}

function headers(token: string): Record<string, string> {
  return { authorization: `Bearer ${token}` };
}

async function postJson(
  request: APIRequestContext,
  token: string,
  path: string,
  data: Record<string, unknown>,
): Promise<Record<string, any>> {
  const response = await request.post(`${API}${path}`, {
    headers: headers(token),
    data,
  });
  expect(response.ok(), `${path}: ${await response.text()}`).toBe(true);
  return response.json();
}

async function createProject(
  request: APIRequestContext,
  token: string,
  prefix: string,
): Promise<Record<string, any>> {
  return postJson(request, token, "/api/projects", {
    name: `${prefix}-${Date.now().toString(36)}`,
  });
}

async function firstOnlineNode(
  request: APIRequestContext,
  token: string,
): Promise<{ id: string; root: string }> {
  const expectedRoot = process.env.E2E_WORKSPACE_ROOT;
  const nodes = await (
    await request.get(`${API}/api/nodes`, { headers: headers(token) })
  ).json();
  for (const node of nodes) {
    const detail = await (
      await request.get(`${API}/api/nodes/${node.id}`, {
        headers: headers(token),
      })
    ).json();
    const root = (detail.workspace_roots ?? []).find(
      (item: { is_enabled: boolean }) => item.is_enabled,
    );
    if (
      detail.status === "online" &&
      root &&
      (!expectedRoot || root.path === expectedRoot)
    ) {
      return { id: node.id, root: root.path };
    }
  }
  throw new Error("no online node with an enabled workspace root");
}

async function moveFromBoard(
  page: Page,
  cardRef: string,
  stage: string,
): Promise<void> {
  await page.locator(`[data-move-for="${cardRef}"]`).click();
  await page
    .locator(`[data-card-ref="${cardRef}"] [data-move-to="${stage}"]`)
    .click();
}

test.describe("V2.1 task layer", () => {
  test.skip(!enabled, "requires E2E_TASKS=1 and CLIORA_PROJECTS_ENABLED=true");

  test("roadmap keeps both unclassified buckets and task detail is independent", async ({
    page,
    request,
  }) => {
    const token = await tokenFor(request);
    const project = await createProject(request, token, "task-roadmap");
    const epic = await postJson(
      request,
      token,
      `/api/projects/${project.id}/epics`,
      { title: "Delivery epic" },
    );
    const story = await postJson(
      request,
      token,
      `/api/projects/${project.id}/user-stories`,
      { title: "Operator story", epic_id: epic.id },
    );
    const nested = await postJson(
      request,
      token,
      `/api/projects/${project.id}/tasks`,
      { title: "Nested task", epic_id: epic.id, user_story_id: story.id },
    );
    await postJson(request, token, `/api/projects/${project.id}/tasks`, {
      title: "Epic bucket task",
      epic_id: epic.id,
    });
    await postJson(request, token, `/api/projects/${project.id}/tasks`, {
      title: "Top bucket task",
    });

    await signIn(page);
    await page.goto(`/projects/${project.id}?tab=roadmap`);
    await expect(page.locator("[data-roadmap-summary]")).toContainText("0 / 3");
    await expect(page.locator('[data-bucket="epic"]')).toContainText(
      "Epic bucket task",
    );
    await expect(page.locator('[data-bucket="top"]')).toContainText(
      "Top bucket task",
    );

    await page.getByRole("button", { name: "Board" }).click();
    await page
      .locator(`[data-card-ref="${nested.task.card_ref}"] .card-open`)
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/projects/${project.id}/tasks/${nested.task.id}$`),
    );
    await expect(
      page.getByRole("heading", { name: "Nested task" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Agent 執行" })).toBeVisible();
    await page.screenshot({
      path: "../artifacts/tk/local/task-detail.png",
      fullPage: true,
    });
  });

  test("dependency refusal names the card and a stale tab rolls back", async ({
    page,
    request,
  }) => {
    const token = await tokenFor(request);
    const project = await createProject(request, token, "task-conflict");
    const prerequisite = await postJson(
      request,
      token,
      `/api/projects/${project.id}/tasks`,
      { title: "Unfinished prerequisite" },
    );
    const dependent = await postJson(
      request,
      token,
      `/api/projects/${project.id}/tasks`,
      { title: "Blocked dependent", stage: "ready" },
    );
    await postJson(
      request,
      token,
      `/api/tasks/${dependent.task.id}/dependencies`,
      { depends_on_task_id: prerequisite.task.id },
    );
    const conflict = await postJson(
      request,
      token,
      `/api/projects/${project.id}/tasks`,
      { title: "Two-tab card" },
    );

    await signIn(page);
    await page.goto(`/projects/${project.id}?tab=board`);
    await moveFromBoard(page, dependent.task.card_ref, "implementing");
    await expect(page.locator(".toast.k-error")).toContainText(
      prerequisite.task.card_ref,
    );
    await expect(
      page.locator(
        `[data-stage="ready"] [data-card-ref="${dependent.task.card_ref}"]`,
      ),
    ).toBeVisible();

    const stalePage = await page.context().newPage();
    await stalePage.goto(`/projects/${project.id}?tab=board`);
    await expect(
      stalePage.locator(`[data-card-ref="${conflict.task.card_ref}"]`),
    ).toBeVisible();
    await moveFromBoard(page, conflict.task.card_ref, "ready");
    await expect(
      page.locator(
        `[data-stage="ready"] [data-card-ref="${conflict.task.card_ref}"]`,
      ),
    ).toBeVisible();
    await moveFromBoard(stalePage, conflict.task.card_ref, "blocked");
    await expect(stalePage.locator(".toast.k-error")).toContainText(
      "剛被別人改過",
    );
    await expect(
      stalePage.locator(
        `[data-stage="ready"] [data-card-ref="${conflict.task.card_ref}"]`,
      ),
    ).toBeVisible();
    await stalePage.close();
  });

  // `the two queued waiting reasons remain different on the board` lived here and was
  // **deleted in `beta.2`**. It had already stopped testing anything: it drove
  // `/projects/:id?tab=board` and read `.waiting-copy`, and both went with
  // `ProjectDetailView.vue` in V2-P1 — but nothing noticed, because an e2e needs a stack
  // and the stack was not run between the deletion and now.
  //
  // **That is the finding, not the deletion.** A test aimed at a deleted screen does not
  // fail; it simply never runs, and a suite that never runs looks the same as one that
  // passes.
  //
  // The property it defended — "the agent you named is offline" and "no agent is
  // eligible" read differently — now lives in three places that do run:
  // `src/modules/work/attention.ts` (levels 5 and 6, with their own copy),
  // `quickFilters.ts` (each is its own filter), and journey J15 against a real daemon.

  test("a requirement proposal can be accepted one task at a time", async ({
    page,
    request,
  }) => {
    const token = await tokenFor(request);
    const project = await createProject(request, token, "requirement");
    await signIn(page);
    await page.goto(`/projects/${project.id}?tab=requirements`);
    await page.locator("[data-new-requirement]").fill("Make retries visible");
    await page.getByRole("button", { name: "提出" }).click();
    await page.getByRole("link", { name: /Make retries visible/ }).click();

    await page
      .locator("[data-spec-criteria]")
      .fill(JSON.stringify([{ id: "AC-1", text: "A retry can be requested" }]));
    await page.getByRole("button", { name: "儲存新版本" }).click();
    await page.getByRole("button", { name: "核准規格" }).click();
    await page.locator("[data-proposal-tree]").fill(
      JSON.stringify({
        tasks: [
          { id: "one", title: "First proposed task" },
          { id: "two", title: "Second proposed task" },
        ],
      }),
    );
    await page.getByRole("button", { name: "建立提案" }).click();
    await page.getByLabel("Second proposed task").uncheck();
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "接受所選任務" }).click();
    await expect(page.getByRole("status")).toContainText("已建立 1 張任務卡");
    await expect(page.getByText(/提案 v1 · partially_accepted/)).toBeVisible();
    await page.screenshot({
      path: "../artifacts/tk/local/requirement-partial-acceptance.png",
      fullPage: true,
    });
  });

  test("a task session projects bounded context twice without dirtying git", async ({
    page,
    request,
  }) => {
    const token = await tokenFor(request);
    const project = await createProject(request, token, "task-context");
    const node = await firstOnlineNode(request, token);
    expect(process.env.E2E_WORKSPACE_ROOT).toBe(node.root);
    await postJson(request, token, `/api/projects/${project.id}/workspaces`, {
      node_id: node.id,
      path: node.root,
    });
    const task = await postJson(
      request,
      token,
      `/api/projects/${project.id}/tasks`,
      {
        title: "Projected task",
        acceptance_criteria: [
          { id: "AC-1", text: "First criterion survives projection" },
          { id: "AC-2", text: "Second criterion survives projection" },
        ],
      },
    );

    execFileSync("git", ["init", "-q"], { cwd: node.root });
    execFileSync("git", ["add", "."], { cwd: node.root });
    execFileSync(
      "git",
      [
        "-c",
        "user.name=Cliora E2E",
        "-c",
        "user.email=e2e@cliora.invalid",
        "commit",
        "-qm",
        "baseline",
      ],
      { cwd: node.root },
    );

    const start = (name: string): Promise<Record<string, any>> =>
      postJson(request, token, "/api/sessions", {
        node_id: node.id,
        runtime: "claude",
        name,
        workspace: node.root,
        project_id: project.id,
        task_id: task.task.id,
        rows: 24,
        columns: 80,
      });
    const first = await start("project-context-one");
    expect(first.context_projection).toBe("ok");
    const context = readFileSync(
      join(node.root, ".cliora", "context", `${first.id}.md`),
      "utf8",
    );
    expect(Buffer.byteLength(context)).toBeLessThanOrEqual(4096);
    expect(context).toContain("First criterion survives projection");
    expect(context).toContain("Second criterion survives projection");
    expect(
      statSync(join(node.root, ".cliora", "context", `${first.id}.token`))
        .mode & 0o777,
    ).toBe(0o600);
    const processFilesBefore = execFileSync(
      "find",
      [join(node.root, ".cliora", "process"), "-type", "f", "-printf", "%P\\n"],
      { encoding: "utf8" },
    );

    const second = await start("project-context-two");
    expect(second.context_projection).toBe("ok");
    expect(
      statSync(
        join(node.root, ".cliora", "context", `${second.id}.md`),
      ).isFile(),
    ).toBe(true);
    expect(
      execFileSync(
        "find",
        [
          join(node.root, ".cliora", "process"),
          "-type",
          "f",
          "-printf",
          "%P\\n",
        ],
        { encoding: "utf8" },
      ),
    ).toBe(processFilesBefore);
    expect(
      execFileSync("git", ["status", "--porcelain"], {
        cwd: node.root,
        encoding: "utf8",
      }),
    ).toBe("");

    await signIn(page);
    await page.goto(`/sessions/${first.id}`);
    await expect(page.locator('[data-context-projection="ok"]')).toContainText(
      ".cliora/context/",
    );
    await expect(
      page.getByRole("link", { name: task.task.card_ref }),
    ).toBeVisible();
  });

  // **Repointed at `work-items` in `beta.2`** (ADR 0044). M1's threshold was set on
  // `/board`, and this is the one measurement in the suite that goes over live HTTP
  // rather than against a service function — which is why it was kept and repointed
  // instead of deleted when the endpoint went. The numbers it writes are therefore
  // **not comparable across the sunset**, and `artifacts/tk/local/m1-live.json` records
  // which endpoint produced them.
  test("M1 records p50 and p95 for a real 200-card board", async ({
    request,
  }) => {
    test.setTimeout(60_000);
    const token = await tokenFor(request);
    const project = await createProject(request, token, "board-m1");
    const createOne = (index: number) =>
      postJson(request, token, `/api/projects/${project.id}/tasks`, {
        title: `M1 task ${index}`,
        stage: ["backlog", "blocked", "ready"][index % 3],
      });
    for (let start = 0; start < 200; start += 10) {
      await Promise.all(
        Array.from({ length: 10 }, (_, offset) =>
          createOne(start + offset + 1),
        ),
      );
    }

    const boardUrl = `${API}/api/projects/${project.id}/work-items`;
    for (let index = 0; index < 5; index += 1) {
      const warmup = await request.get(boardUrl, { headers: headers(token) });
      expect(warmup.ok()).toBe(true);
    }
    const timings: number[] = [];
    let responseBytes = 0;
    for (let index = 0; index < 50; index += 1) {
      const started = performance.now();
      const response = await request.get(boardUrl, { headers: headers(token) });
      const body = await response.body();
      timings.push(performance.now() - started);
      expect(response.ok()).toBe(true);
      responseBytes = body.byteLength;
    }
    timings.sort((left, right) => left - right);
    const percentile = (value: number): number =>
      timings[Math.ceil(timings.length * value) - 1];
    const result = {
      cards: 200,
      samples: timings.length,
      // Which endpoint produced these. `/board` until `beta.2` deleted it; the budget
      // below was set against that shape, so a reader comparing an old file to a new one
      // needs this line to know the two are different measurements.
      endpoint: "work-items",
      transport: "live HTTP over loopback; response body read",
      response_bytes: responseBytes,
      p50_ms: Number(percentile(0.5).toFixed(2)),
      p95_ms: Number(percentile(0.95).toFixed(2)),
      threshold_bytes: 512 * 1024,
      threshold_p95_ms: 400,
    };
    writeFileSync(
      "../artifacts/tk/local/m1-live.json",
      `${JSON.stringify(result, null, 2)}\n`,
    );
    expect(result.response_bytes).toBeLessThanOrEqual(result.threshold_bytes);
    expect(result.p95_ms).toBeLessThanOrEqual(result.threshold_p95_ms);
  });
});
