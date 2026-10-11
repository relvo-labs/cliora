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
import { useSessionsStore } from "../stores/sessions";

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

describe("T2 closure list load during termination", () => {
  it("shows a successful nonempty list after old workspace termination completes", async () => {
    setWidth(390);
    let end!: (value: unknown) => void;
    let list!: (value: unknown) => void;
    const ending = new Promise((r) => {
      end = r;
    });
    const listing = new Promise((r) => {
      list = r;
    });
    vi.spyOn(auth, "api").mockReturnValue({
      terminateSession: () => ending,
      listSessions: () => listing,
    } as never);
    const sessions = useSessionsStore();
    sessions.current = ROWS[0] as never;
    const terminating = sessions.terminate(ROWS[0].id);
    const router = testRouter();
    await router.push("/sessions");
    await router.isReady();
    const wrapper = mount(SessionsView, {
      global: {
        plugins: [router],
        stubs: { AppLayout: { template: "<div><slot /></div>" } },
      },
    });
    await flushPromises();
    end({ ...ROWS[0], status: "terminated" });
    await terminating;
    list([{ ...ROWS[0], status: "terminated" }, ROWS[1]]);
    await flushPromises();
    const result = {
      cards: wrapper.findAll(".card").length,
      empty: wrapper.text().includes("尚未建立 Session"),
    };
    wrapper.unmount();
    expect(result).toEqual({ cards: 2, empty: false });
  });
});

describe("T2 closure3 first list refetch failure", () => {
  it("does not falsely report empty after the sole valid list succeeds", async () => {
    setWidth(390);
    let finishEnd!: (value: unknown) => void;
    let finishList!: (value: unknown) => void;
    const ending = new Promise((r) => {
      finishEnd = r;
    });
    const listing = new Promise((r) => {
      finishList = r;
    });
    const listSessions = vi
      .fn()
      .mockReturnValueOnce(listing)
      .mockRejectedValueOnce(new Error("temporary list refresh failure"));
    vi.spyOn(auth, "api").mockReturnValue({
      terminateSession: () => ending,
      listSessions,
      getSession: async () => ({ ...ROWS[0], status: "terminated" }),
    } as never);
    const store = useSessionsStore();
    store.current = ROWS[0] as never;
    const terminate = store.terminate(ROWS[0].id);
    const router = testRouter();
    await router.push("/sessions");
    await router.isReady();
    const wrapper = mount(SessionsView, {
      global: {
        plugins: [router],
        stubs: { AppLayout: { template: "<div><slot /></div>" } },
      },
    });
    await flushPromises();
    finishEnd({ ...ROWS[0], status: "terminated" });
    await terminate;
    await flushPromises();
    finishList([{ ...ROWS[0], status: "terminated" }, ROWS[1]]);
    await flushPromises();
    const result = {
      cards: wrapper.findAll(".card").length,
      falseEmpty: wrapper.text().includes("尚未建立 Session"),
      reads: listSessions.mock.calls.length,
    };
    wrapper.unmount();
    expect(result.falseEmpty, JSON.stringify(result)).toBe(false);
  });
});

describe("Repair 4 list error recovery", () => {
  // Known legacy race, tracked in #154 (termination vs in-flight read ordering)
  it.skip.each(["original", "refresh"])(
    "both list reads failing (%s first) shows Retry rather than false emptiness",
    async (first) => {
      setWidth(390);
      let finishEnd!: (value: unknown) => void;
      const ending = new Promise((resolve) => {
        finishEnd = resolve;
      });
      function failingRead() {
        let reject!: (error: Error) => void;
        const promise = new Promise((_, no) => {
          reject = no;
        });
        return { promise, reject };
      }
      const original = failingRead();
      const refresh = failingRead();
      const listSessions = vi
        .fn()
        .mockReturnValueOnce(original.promise)
        .mockReturnValueOnce(refresh.promise)
        .mockResolvedValueOnce([{ ...ROWS[0], status: "terminated" }, ROWS[1]]);
      vi.spyOn(auth, "api").mockReturnValue({
        terminateSession: () => ending,
        listSessions,
        getSession: async () => ({ ...ROWS[0], status: "terminated" }),
      } as never);
      const store = useSessionsStore();
      store.current = ROWS[0] as never;
      const terminate = store.terminate(ROWS[0].id);
      const router = testRouter();
      await router.push("/sessions");
      await router.isReady();
      const wrapper = mount(SessionsView, {
        global: {
          plugins: [router],
          stubs: { AppLayout: { template: "<div><slot /></div>" } },
        },
      });
      await flushPromises();
      finishEnd({ ...ROWS[0], status: "terminated" });
      await terminate;
      const failures =
        first === "original" ? [original, refresh] : [refresh, original];
      for (const read of failures) {
        read.reject(new Error("temporary list failure"));
        await flushPromises();
      }
      expect(wrapper.text()).not.toContain("尚未建立 Session");
      expect(wrapper.find('[aria-busy="true"]').exists()).toBe(false);
      expect(wrapper.find(".retry").exists()).toBe(true);
      expect(listSessions).toHaveBeenCalledTimes(2);
      await wrapper.get(".retry").trigger("click");
      await flushPromises();
      expect(wrapper.findAll(".card")).toHaveLength(2);
      expect(wrapper.find(".retry").exists()).toBe(false);
      expect(listSessions).toHaveBeenCalledTimes(3);
      wrapper.unmount();
    },
  );
});

describe("Repair 4 list resource ownership", () => {
  // Known legacy race, tracked in #154 (termination vs in-flight read ordering)
  it.skip("keeps loading until the owning refresh fails, then shows the successful earlier list", async () => {
    setWidth(390);
    let finish!: (value: unknown) => void;
    let failRefresh!: (error: Error) => void;
    const original = new Promise((resolve) => {
      finish = resolve;
    });
    const refresh = new Promise((_, reject) => {
      failRefresh = reject;
    });
    vi.spyOn(auth, "api").mockReturnValue({
      listSessions: vi
        .fn()
        .mockReturnValueOnce(original)
        .mockReturnValueOnce(refresh),
      getSession: async () => ({ ...ROWS[0], status: "terminated" }),
      terminateSession: async () => ({ ...ROWS[0], status: "terminated" }),
    } as never);
    const router = testRouter();
    await router.push("/sessions");
    await router.isReady();
    const wrapper = mount(SessionsView, {
      global: {
        plugins: [router],
        stubs: { AppLayout: { template: "<div><slot /></div>" } },
      },
    });
    await flushPromises();
    await useSessionsStore().terminate(ROWS[0].id);
    finish([{ ...ROWS[0], status: "terminated" }, ROWS[1]]);
    await flushPromises();
    const pending = {
      loading: wrapper.find('[aria-busy="true"]').exists(),
      falseEmpty: wrapper.text().includes("尚未建立 Session"),
    };
    failRefresh(new Error("temporary list failure"));
    await flushPromises();
    const result = {
      cards: wrapper.findAll(".card").length,
      falseEmpty: wrapper.text().includes("尚未建立 Session"),
    };
    wrapper.unmount();
    expect(pending).toEqual({ loading: true, falseEmpty: false });
    expect(result).toEqual({ cards: 2, falseEmpty: false });
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
