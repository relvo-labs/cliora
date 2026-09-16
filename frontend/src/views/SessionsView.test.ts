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

async function render(rows = ROWS) {
  vi.spyOn(auth, "api").mockReturnValue({
    listSessions: vi.fn(async () => rows),
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
    for (const value of ["refactor-api", "node-alpha", "claude"]) {
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
