// The session list has two presentations of one dataset (plan/29 MS-04).
//
// The rule these cases exist to hold is narrow: below 768px the layout changes
// and the *information* does not. A five-column table at 390px is not unusable
// because it overflows — UiDataTable scrolls its own box, so the page stays
// intact — it is unusable because only the first column is legible and the
// other four are behind a gesture nothing on screen suggests. Dropping columns
// to "fit" would have been the easy version of this ticket and the wrong one.

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import * as auth from "../stores/auth";
import { useAuthStore } from "../stores/auth";
import SessionsView from "./SessionsView.vue";

const ROWS = [
  {
    id: "44444444-4444-4444-8444-444444444444",
    name: "refactor-api",
    node_id: "node-alpha",
    user_id: "u",
    runtime: "claude",
    workspace: "/srv/work/api",
    status: "running",
    started_at: "2026-09-14T00:00:00Z",
    last_activity_at: "2026-09-14T00:01:00Z",
  },
  {
    id: "55555555-5555-4555-8555-555555555555",
    name: "docs-pass",
    node_id: "node-beta",
    user_id: "u",
    runtime: "codex",
    workspace: "/srv/work/docs",
    status: "stopped",
    started_at: "2026-09-14T00:00:00Z",
    last_activity_at: null,
  },
];

function setWidth(px: number): void {
  Object.defineProperty(window, "innerWidth", {
    value: px,
    configurable: true,
    writable: true,
  });
}

function testRouter(): Router {
  const blank = { template: "<div/>" };
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/sessions", name: "sessions", component: SessionsView },
      { path: "/sessions/:id", name: "session-workspace", component: blank },
    ],
  });
}

// The node list the page reads to name each row's node (#105).
const NODES = [
  { id: "node-alpha", name: "build-vm", hostname: "build-vm.internal" },
  { id: "node-beta", name: "docs-vm", hostname: "docs-vm.internal" },
];

async function render(
  rows = ROWS,
  listNodes: () => Promise<unknown> = async () => NODES,
) {
  vi.spyOn(auth, "api").mockReturnValue({
    listSessions: vi.fn(async () => rows),
    listNodes: vi.fn(listNodes),
  } as never);
  const store = useAuthStore();
  store.user = {
    id: "u",
    username: "u",
    display_name: "U",
    role: "Admin",
    permissions: ["session.create"],
  };
  const router = testRouter();
  router.push("/sessions");
  await router.isReady();
  const wrapper = mount(SessionsView, {
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.restoreAllMocks();
});

describe("SessionsView — 行動卡片清單", () => {
  it("窄視窗用卡片，桌面維持表格", async () => {
    setWidth(390);
    const narrow = await render();
    expect(narrow.findAll(".card")).toHaveLength(2);
    expect(narrow.find("table").exists()).toBe(false);

    setWidth(1440);
    const wide = await render();
    // The desktop DOM is unchanged by this ticket, and that is the constraint
    // rather than a side effect.
    expect(wide.find("table").exists()).toBe(true);
    expect(wide.findAll(".card")).toHaveLength(0);
  });

  it("六個欄位一個都沒少", async () => {
    setWidth(390);
    const wrapper = await render();
    const first = wrapper.findAll(".card")[0];
    const text = first.text();
    for (const value of ["refactor-api", "build-vm", "claude"]) {
      expect(text, `${value} 不見了`).toContain(value);
    }
    // The path is in the DOM with its full value in `title`, because the card
    // truncates it visually.
    expect(first.find(".card-path").attributes("title")).toBe("/srv/work/api");
    // Status is a badge rather than bare text, same component the table uses.
    expect(first.find(".badge").exists()).toBe(true);
    // Last activity is rendered through the shared formatter; asserting the
    // exact string would pin a locale, so this asserts it is not blank.
    expect(first.find(".card-meta").text().length).toBeGreaterThan(0);
  });

  it("整張卡片是控制項，不是只有名稱可點", async () => {
    setWidth(390);
    const wrapper = await render();
    const card = wrapper.findAll(".card")[0];
    expect(card.element.tagName).toBe("BUTTON");
    await card.trigger("click");
    await flushPromises();
    const router = wrapper.vm.$router as Router;
    expect(router.currentRoute.value.name).toBe("session-workspace");
    expect(router.currentRoute.value.params.id).toBe(ROWS[0].id);
  });

  it("沒有符合條件時，兩種呈現都說得出下一步", async () => {
    setWidth(390);
    const wrapper = await render();
    await wrapper.get('input[type="search"]').setValue("nothing-matches-this");
    await flushPromises();
    expect(wrapper.findAll(".card")).toHaveLength(0);
    expect(wrapper.text()).toContain("沒有符合條件的項目");
    // And the way out is offered, not just described.
    expect(wrapper.text()).toContain("清除搜尋與篩選");
  });

  it("空清單與無搜尋結果是兩種不同的狀態", async () => {
    setWidth(390);
    const empty = await render([]);
    expect(empty.text()).toContain("尚未建立 Session");
    expect(empty.text()).not.toContain("沒有符合條件的項目");
  });
});

// #105: the card reversed absolute paths (`direction: rtl` let the bidi
// algorithm move the leading "/" to the end) and named the node by its UUID.
describe("SessionsView — 卡片的路徑與 Node 名稱 (#105)", () => {
  const UUID_ROWS = ROWS.map((row, i) => ({
    ...row,
    node_id: i === 0 ? "26ae21b0-78a3-4352-a5f4-c25e400fa95b" : row.node_id,
  }));
  const UUID_NODES = [
    { ...NODES[0], id: "26ae21b0-78a3-4352-a5f4-c25e400fa95b" },
    NODES[1],
  ];

  it("names the node, not its UUID, on the card and in the table", async () => {
    setWidth(390);
    const narrow = await render(UUID_ROWS, async () => UUID_NODES);
    const meta = narrow.findAll(".card")[0].find(".card-meta").text();
    expect(meta).toContain("build-vm");
    expect(meta).not.toContain("26ae21b0-78a3-4352-a5f4-c25e400fa95b");

    setWidth(1440);
    const wide = await render(UUID_ROWS, async () => UUID_NODES);
    const row = wide.findAll("tbody tr")[0].text();
    expect(row).toContain("build-vm");
    expect(row).not.toContain("26ae21b0-78a3-4352-a5f4-c25e400fa95b");
  });

  it("does not print a full UUID when the node list cannot be read", async () => {
    setWidth(390);
    const wrapper = await render(UUID_ROWS, async () => {
      throw new Error("offline");
    });
    const card = wrapper.findAll(".card")[0];
    // The list itself still renders: naming a node is not worth losing it.
    expect(card.find(".card-name").text()).toBe("refactor-api");
    const node = card.find(".card-node");
    expect(node.text()).not.toContain("26ae21b0-78a3-4352-a5f4-c25e400fa95b");
    expect(node.text()).toContain("26ae21b0");
    // The whole id stays reachable rather than being thrown away.
    expect(node.attributes("title")).toBe(
      "26ae21b0-78a3-4352-a5f4-c25e400fa95b",
    );
  });

  it("isolates the path as left-to-right text so its leading / stays first", async () => {
    setWidth(390);
    const wrapper = await render();
    const path = wrapper.findAll(".card")[0].find(".card-path");
    // The start-truncating container may be right-to-left; the path inside it
    // must be its own left-to-right run, or the bidi algorithm reorders the
    // neutral "/" characters.
    const run = path.find('bdi[dir="ltr"]');
    expect(run.exists(), "path is not an isolated LTR run").toBe(true);
    expect(run.text()).toBe("/srv/work/api");
  });
});
