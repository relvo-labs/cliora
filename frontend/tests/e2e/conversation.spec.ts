import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { writeFileSync, chmodSync } from "node:fs";

// V2-C1's browser proof: the three journeys whose subject is something a person sees
// (`plan/24/03`, D69). The other four are scripts under `scripts/cv/journeys/`, because
// their subject is timing or concurrency a browser has no control over.
//
// **J1a is the one that must not be downgraded** — exit condition 11 says three rounds of
// clarification, a spec proposal, a request for changes and an acceptance all happen in
// one screen, and only a browser can say that.
//
// Requires a runner-mode stack: `E2E_RUNNER=1 scripts/e2e/run-stack.sh`, which also
// exports `E2E_AGENT_SCRIPT` — the file `fakecli` runs as "the agent". One file for the
// whole stack, so these tests must not run in parallel with each other; the suite is
// invoked with `--workers=1` for exactly this reason.
const enabled = process.env.E2E_CONVERSATION === "1";
const adminUser = process.env.E2E_ADMIN_USER ?? "e2e-admin";
const adminPass = process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-pw";
const API =
  process.env.E2E_API_URL ??
  process.env.E2E_BASE_URL ??
  "http://127.0.0.1:8000";
const AGENT_SCRIPT = process.env.E2E_AGENT_SCRIPT ?? "";
const REPO =
  process.env.E2E_REPO_ROOT ?? process.cwd().replace(/\/frontend$/, "");

/** The default agent: reads the thread, decides what this round does (`clarify.sh`). */
const CLARIFYING_AGENT = `#!/usr/bin/env bash\nexec "${REPO}/scripts/cv/agent/clarify.sh"\n`;

/**
 * An agent that asks a question and then fails.
 *
 * Its exit status is what makes the run fail: the daemon judges a run by the child's
 * exit code, and `fakecli` carries a script's status out for this reason (`CE-01` ②).
 */
const FAILING_AGENT = `#!/usr/bin/env bash
set -uo pipefail
cliora task ask "這張卡的驗收標準要用哪一版？"
echo "本輪刻意失敗，用來測失敗後的重新派工"
exit 3
`;

function useAgent(body: string): void {
  if (!AGENT_SCRIPT)
    throw new Error(
      "E2E_AGENT_SCRIPT unset — start the stack with E2E_RUNNER=1",
    );
  writeFileSync(AGENT_SCRIPT, body, "utf8");
  chmodSync(AGENT_SCRIPT, 0o755);
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

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(adminUser);
  await page.locator('input[name="password"]').fill(adminPass);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/(dashboard|nodes|sessions)/);
}

/**
 * A card an agent needs no repository for, already in `ready`.
 *
 * `source: none`, `delivery: none`, and **deliberately not `card_kind: clarification`**:
 * `CreateTaskRequest` has no such field, so passing it was silently ignored and the card
 * was an ordinary implementation card all along. A real clarification card needs a
 * requirement (`TASK_CLARIFICATION_NEEDS_REQUIREMENT`), which is V2.5's flow and not what
 * these journeys are about.
 */
async function bareCard(
  request: APIRequestContext,
  token: string,
  title: string,
): Promise<{ projectId: string; taskId: string; cardRef: string }> {
  const name = `cv-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4)}`;
  const project = await (
    await request.post(`${API}/api/projects`, {
      headers: headers(token),
      data: { name, slug: name },
    })
  ).json();
  const created = await (
    await request.post(`${API}/api/projects/${project.id}/tasks`, {
      headers: headers(token),
      data: {
        title,
        source: "none",
        delivery: "none",
        card_kind: "clarification",
      },
    })
  ).json();
  let task = created.task;
  if (task.stage !== "ready") {
    const moved = await (
      await request.patch(`${API}/api/tasks/${task.id}`, {
        headers: headers(token),
        data: { stage: "ready", version: task.version },
      })
    ).json();
    task = moved.task;
  }
  return { projectId: project.id, taskId: task.id, cardRef: task.card_ref };
}

/**
 * Wait until the card has an open question, then reload so the panel shows it.
 *
 * **The conversation panel does not live-update** — `useConversation` loads on mount and
 * refreshes after a write, and V2-C1 deliberately ships no notification path (`CV-06`, no
 * WSS). So a person who is waiting for an agent's question reloads the page, and a
 * journey that did not would sit in front of a stale panel until it timed out. Asserting
 * on the API first keeps the two failures apart: "the agent never asked" and "the panel
 * never showed it" are different bugs.
 */
async function reloadOnOpenQuestion(
  page: Page,
  request: APIRequestContext,
  token: string,
  taskId: string,
): Promise<void> {
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(
              `${API}/api/tasks/${taskId}/questions?state=open`,
              {
                headers: headers(token),
              },
            )
          ).json()
        ).length,
      { timeout: 120_000, message: "the agent never asked a question" },
    )
    .toBeGreaterThan(0);
  await page.reload();
}

async function runsFor(
  request: APIRequestContext,
  token: string,
  taskId: string,
): Promise<Array<Record<string, any>>> {
  return (
    await request.get(`${API}/api/tasks/${taskId}/runs`, {
      headers: headers(token),
    })
  ).json();
}

async function messagesFor(
  request: APIRequestContext,
  token: string,
  taskId: string,
): Promise<Array<Record<string, any>>> {
  const page = await (
    await request.get(`${API}/api/tasks/${taskId}/messages?limit=500`, {
      headers: headers(token),
    })
  ).json();
  return page.items;
}

test.describe("V2-C1 ticket conversation", () => {
  test.skip(!enabled, "requires E2E_CONVERSATION=1 and a runner-mode stack");

  // Four rounds of a 5-second poll plus a process launch each; the default 30s would
  // time out on the first one.
  test.setTimeout(300_000);

  test("J1a: three rounds, a proposal, a change request and an acceptance — one screen", async ({
    page,
    request,
  }) => {
    useAgent(CLARIFYING_AGENT);
    const token = await tokenFor(request);
    const { projectId, taskId } = await bareCard(
      request,
      token,
      "釐清：登入方式",
    );

    // Every URL this test ever visits, so "never entered the Terminal" is an assertion
    // rather than a habit (exit condition 11's actual words).
    const visited: string[] = [];
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame())
        visited.push(new URL(frame.url()).pathname);
    });

    await signIn(page);
    await page.goto(`/projects/${projectId}/tasks/${taskId}`);
    const conversation = page.locator("section.conversation");
    // Two badges, deliberately: the header says this **card** is waiting, and the
    // QuestionCard in the thread says which **question** is. Located separately so that
    // losing either one is a failure rather than a `.first()` that still passes.
    const headerBadge = page
      .locator("section.conversation > header")
      .getByText("⚠ 等待你的回覆");
    const threadBadge = conversation.locator("ol").getByText("⚠ 等待你的回覆");
    await expect(conversation).toBeVisible();
    // Nothing to answer yet, so the primary action is **absent** rather than disabled —
    // a permanently greyed button reads as broken (`MessageComposer`).
    //
    // Two buttons wear this label once a question *is* open: the QuestionCard's, which
    // only scrolls the composer into view, and the composer's, which sends. The one
    // under test below is the composer's; here neither should exist.
    await expect(page.getByRole("button", { name: /回覆並繼續/ })).toHaveCount(
      0,
    );

    await page.getByRole("button", { name: "派給 Agent" }).click();

    for (const round of [1, 2]) {
      await reloadOnOpenQuestion(page, request, token, taskId);
      await expect(headerBadge).toBeVisible({ timeout: 30_000 });
      await expect(threadBadge).toBeVisible();
      await page
        .locator('textarea[aria-label="訊息內容"]')
        .fill(`第 ${round} 輪的回覆`);
      await page
        .locator("section.conversation .composer")
        .getByRole("button", { name: /回覆並繼續/ })
        .click();
      await expect(page.getByText("已回覆，並排入新的一輪。")).toBeVisible({
        timeout: 30_000,
      });
      // The badge clears once the question is closed — the panel reads the server's
      // questions list, never "was the last message a question".
      await expect(headerBadge).toHaveCount(0, { timeout: 30_000 });
    }

    // Round three proposes a specification. Waited for on the API and then reloaded, for
    // the same reason as the questions above.
    await expect
      .poll(
        async () =>
          (await messagesFor(request, token, taskId)).filter(
            (m) => m.kind === "proposal",
          ).length,
        { timeout: 150_000, message: "the agent never proposed a spec" },
      )
      .toBeGreaterThan(0);
    await page.reload();
    const proposal = conversation
      .locator("article, div")
      .filter({ hasText: "規格提案 v1" });
    await expect(proposal.first()).toBeVisible({ timeout: 120_000 });
    const beforeDecision = await (
      await request.get(`${API}/api/tasks/${taskId}`, {
        headers: headers(token),
      })
    ).json();
    const card = beforeDecision.task ?? beforeDecision;

    await page.getByRole("button", { name: "要求修改" }).click();
    await page
      .locator('textarea[aria-label="要求修改的理由"]')
      .fill("鎖定時間與解鎖方式要寫進驗收標準。");
    await page.getByRole("button", { name: "送出" }).click();

    // **A change request does not start a new turn**, and finding that out is why this
    // journey exists. `plan/23/03` §2 lists `decision` as resuming "依 decision" and ADR
    // 0035's state machine draws `SpecProposed → Clarifying` on it, but nothing in
    // `ConversationService` enqueues a continuation for a decision — only an answer does.
    // So a person who asks for changes has to dispatch the card again, and that is what
    // this journey does rather than waiting for something that will never happen
    // (`plan/24/10` §2.4, `CE-18`).
    await expect
      .poll(
        async () =>
          (await messagesFor(request, token, taskId)).filter(
            (m) => m.kind === "decision",
          ).length,
        { timeout: 30_000, message: "the change request was never written" },
      )
      .toBe(1);
    expect(await runsFor(request, token, taskId)).toHaveLength(3);

    await page.reload();
    await page.getByRole("button", { name: "派給 Agent" }).click();
    await expect
      .poll(
        async () =>
          (await messagesFor(request, token, taskId)).filter(
            (m) => m.kind === "proposal",
          ).length,
        { timeout: 150_000, message: "the agent never revised the spec" },
      )
      .toBe(2);
    await page.reload();
    await expect(
      conversation
        .locator("article")
        .filter({ hasText: "規格提案 v2" })
        .first(),
    ).toBeVisible({ timeout: 30_000 });
    // Only the newest proposal may be acted on; the first one says so.
    await expect(
      conversation.getByText("已被較新的提案取代").first(),
    ).toBeVisible();

    await page.getByRole("button", { name: "接受" }).last().click();
    await expect(conversation.getByText("接受這份規格提案。")).toBeVisible({
      timeout: 30_000,
    });

    // --- what the database has to say ---------------------------------------
    const runs = await runsFor(request, token, taskId);
    // Four rounds happened in this one screen: the dispatch, two answers that each
    // started a turn, and the re-dispatch a change request needs (`CE-18`).
    expect(runs).toHaveLength(4);
    expect(runs.map((run) => run.seq).sort((a, b) => a - b)).toEqual([
      1, 2, 3, 4,
    ]);
    // Two of them ended waiting for a person, which is what "the agent asked and exited"
    // looks like from here (D59).
    expect(
      runs.filter((run) => run.result === "awaiting_input").length,
    ).toBeGreaterThan(0);
    // **`turn_seq` and `parent_run_id` are not on `TaskRunDTO`**, so the browser cannot
    // see which run continued which — a `beta.1` concern for the Drawer, and the reason
    // the continuation chain is asserted by the database-backed journeys instead
    // (`j5_chaos.py`, `j8_concurrent.py`).

    const messages = await messagesFor(request, token, taskId);
    expect(messages.map((m) => m.conversation_seq)).toEqual(
      messages.map((_m, index) => index + 1),
    );
    expect(messages.filter((m) => m.kind === "question")).toHaveLength(2);
    expect(messages.filter((m) => m.kind === "answer")).toHaveLength(2);
    expect(messages.filter((m) => m.kind === "proposal")).toHaveLength(2);
    const decisions = messages.filter((m) => m.kind === "decision");
    expect(decisions).toHaveLength(2);
    // A person wrote them. An agent's `decision` is a 403 (J9), and this is the other
    // side of that assertion.
    expect(decisions.every((m) => m.author_kind === "user")).toBe(true);

    // **A proposal changes no readiness, and neither does a decision.** Readiness moves
    // through V2.5's human-only endpoints; `plan/23/08` §4 said "only the human decision
    // moves readiness", which describes something deliberately not implemented
    // (`plan/24/03` §0.2).
    const after = await (
      await request.get(`${API}/api/tasks/${taskId}`, {
        headers: headers(token),
      })
    ).json();
    const finalCard = after.task ?? after;
    expect(finalCard.stage).toBe(card.stage);
    expect(finalCard.gates).toEqual(card.gates);

    // Not once in the Terminal.
    expect(visited.filter((path) => path.startsWith("/sessions"))).toEqual([]);
  });

  test("J3: the agent asks, and the card says a person is being waited on", async ({
    page,
    request,
  }) => {
    useAgent(CLARIFYING_AGENT);
    const token = await tokenFor(request);
    const { projectId, taskId } = await bareCard(
      request,
      token,
      "釐清：等待狀態",
    );

    await signIn(page);
    await page.goto(`/projects/${projectId}/tasks/${taskId}`);
    await page.getByRole("button", { name: "派給 Agent" }).click();

    await reloadOnOpenQuestion(page, request, token, taskId);
    const conversation = page.locator("section.conversation");
    await expect(
      page
        .locator("section.conversation > header")
        .getByText("⚠ 等待你的回覆"),
    ).toBeVisible({ timeout: 30_000 });
    await expect(
      conversation.locator("ol").getByText("⚠ 等待你的回覆"),
    ).toBeVisible();

    // The server computed it, and the projection columns say so. The panel does not read
    // them yet — `CV-13` writes them for `beta.1` — so this half is asserted on the API
    // and the visible half above (`plan/24/03` §0.1).
    const detail = await (
      await request.get(`${API}/api/tasks/${taskId}`, {
        headers: headers(token),
      })
    ).json();
    const card = detail.task ?? detail;
    expect(card.waiting_for_actor).toBe("human");
    expect(card.open_question_count).toBe(1);

    // The run that asked has **ended**, and the card still says it is waiting. Those two
    // facts holding at once is what this milestone is for.
    const runs = await runsFor(request, token, taskId);
    expect(runs).toHaveLength(1);
    expect(runs[0].status).toBe("succeeded");
    expect(runs[0].result).toBe("awaiting_input");

    // Reloading changes nothing: the badge is not a piece of in-memory state.
    await page.reload();
    await expect(
      page
        .locator("section.conversation > header")
        .getByText("⚠ 等待你的回覆"),
    ).toBeVisible();
  });

  test("J7: a failed run shows why, and the conversation survives a retry", async ({
    page,
    request,
  }) => {
    useAgent(FAILING_AGENT);
    const token = await tokenFor(request);
    const { projectId, taskId } = await bareCard(
      request,
      token,
      "釐清：失敗後重派",
    );

    await signIn(page);
    await page.goto(`/projects/${projectId}/tasks/${taskId}`);
    await page.getByRole("button", { name: "派給 Agent" }).click();

    // The question arrives first, then the process fails.
    await reloadOnOpenQuestion(page, request, token, taskId);
    const conversation = page.locator("section.conversation");
    await expect(conversation.getByText(/驗收標準要用哪一版/)).toBeVisible({
      timeout: 30_000,
    });
    await expect
      .poll(async () => (await runsFor(request, token, taskId))[0]?.status, {
        timeout: 90_000,
        message: "the run never reached failed",
      })
      .toBe("failed");

    // A failed run does not close the question it asked: nobody answered it, and a card
    // that looks idle while a question is outstanding is the worse of the two states.
    const questions = await (
      await request.get(`${API}/api/tasks/${taskId}/questions?state=open`, {
        headers: headers(token),
      })
    ).json();
    expect(questions).toHaveLength(1);

    await page.reload();
    // The reason is on screen, and the thread is intact.
    await expect(page.getByText(/失敗|failed/i).first()).toBeVisible();
    await expect(conversation.getByText(/驗收標準要用哪一版/)).toBeVisible();

    const seqBefore = (await messagesFor(request, token, taskId)).map(
      (m) => m.conversation_seq,
    );

    // Dispatch again, with an agent that succeeds this time.
    useAgent(CLARIFYING_AGENT);
    await page.getByRole("button", { name: "派給 Agent" }).click();
    await expect
      .poll(async () => (await runsFor(request, token, taskId)).length, {
        timeout: 90_000,
        message: "the second dispatch never produced a run",
      })
      .toBeGreaterThan(1);

    const messages = await messagesFor(request, token, taskId);
    const seqAfter = messages.map((m) => m.conversation_seq);
    // The sequence continues; it does not restart, and nothing from the failed round was
    // dropped.
    expect(seqAfter.slice(0, seqBefore.length)).toEqual(seqBefore);
    expect(seqAfter).toEqual(messages.map((_m, index) => index + 1));
  });
});
