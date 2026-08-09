import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { ApiError } from "../api/client";
import { AUDIT_ACTIONS, type AuditItem, type AuditPage } from "../api/dto";
import { useAuthStore } from "../stores/auth";
import * as auth from "../stores/auth";
import { ACTION_GROUPS, ungroupedActions } from "../utils/auditActions";
import AuditView from "./AuditView.vue";

function item(overrides: Partial<AuditItem> = {}): AuditItem {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    action: "node.remove",
    created_at: "2026-07-25T11:59:00Z",
    actor: {
      id: "22222222-2222-4222-8222-222222222222",
      username: "admin",
      display_name: "Admin User",
    },
    node: { id: "33333333-3333-4333-8333-333333333333", name: "build-01" },
    session_id: null,
    request_id: "01K0REQUEST",
    metadata: { reason: "maintenance" },
    ...overrides,
  };
}

function page(items: AuditItem[], next: string | null = null): AuditPage {
  return { items, next_cursor: next };
}

// A real router: the view reads and writes the filter through the query string.
function testRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/audit", name: "audit", component: AuditView },
      { path: "/nodes", name: "nodes", component: { template: "<div/>" } },
      {
        path: "/nodes/:id",
        name: "node-detail",
        component: { template: "<div/>" },
      },
      {
        path: "/sessions/:id",
        name: "session-workspace",
        component: { template: "<div/>" },
      },
    ],
  });
}

async function render(
  listAudit: ReturnType<typeof vi.fn>,
  query: Record<string, string> = {},
) {
  vi.spyOn(auth, "api").mockReturnValue({
    listAudit,
  } as unknown as ReturnType<typeof auth.api>);
  const router = testRouter();
  await router.push({ path: "/audit", query });
  await router.isReady();
  const wrapper = mount(AuditView, {
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return { wrapper, router };
}

describe("AuditView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const store = useAuthStore();
    store.user = {
      id: "u",
      username: "admin",
      display_name: "Admin",
      role: "Admin",
      permissions: ["audit.view"],
      features: [],
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders rows with resolved names, both the label and the raw code", async () => {
    const { wrapper } = await render(vi.fn().mockResolvedValue(page([item()])));
    const text = wrapper.text();
    expect(text).toContain("移除 Node");
    // The raw key stays visible: it is what an operator types into a filter or
    // greps for in the log.
    expect(text).toContain("node.remove");
    expect(text).toContain("Admin User");
    expect(text).toContain("build-01");
  });

  it("labels the time column with the viewer's time zone", async () => {
    // A localized timestamp without its zone is ambiguous the moment it is copied
    // into a ticket or compared with a server log.
    const { wrapper } = await render(vi.fn().mockResolvedValue(page([item()])));
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(wrapper.find("thead").text()).toContain(zone);
    // The exact instant stays available as a tooltip.
    expect(wrapper.find("tbody td").attributes("title")).toBe(
      "2026-07-25T11:59:00Z",
    );
  });

  it("shows the loading state before the first response", async () => {
    vi.spyOn(auth, "api").mockReturnValue({
      listAudit: vi.fn().mockReturnValue(new Promise(() => {})),
    } as unknown as ReturnType<typeof auth.api>);
    const router = testRouter();
    await router.push("/audit");
    const wrapper = mount(AuditView, {
      global: {
        plugins: [router],
        stubs: { AppLayout: { template: "<div><slot /></div>" } },
      },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("正在查詢");
    expect(wrapper.find("table").exists()).toBe(false);
  });

  it("explains an empty result and suggests widening the filter", async () => {
    const { wrapper } = await render(vi.fn().mockResolvedValue(page([])));
    expect(wrapper.text()).toContain("此條件下沒有紀錄");
    expect(wrapper.text()).toContain("放寬時間範圍");
    expect(wrapper.find("table").exists()).toBe(false);
  });

  it("shows a forbidden state with a way back for a non-Admin", async () => {
    const { wrapper } = await render(
      vi.fn().mockRejectedValue(new ApiError("FORBIDDEN", "no", 403)),
    );
    expect(wrapper.text()).toContain("只有 Admin");
    expect(wrapper.text()).toContain("返回 Nodes");
  });

  it("shows the request id and a retry on failure", async () => {
    const listAudit = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(
          "INTERNAL_ERROR",
          "An internal error occurred",
          500,
          "rid-7",
        ),
      )
      .mockResolvedValueOnce(page([item()]));
    const { wrapper } = await render(listAudit);

    expect(wrapper.text()).toContain("rid-7");
    const retry = wrapper
      .findAll("button")
      .find((button) => button.text() === "重試");
    await retry?.trigger("click");
    await flushPromises();
    expect(wrapper.find("table").exists()).toBe(true);
  });

  it("keeps loaded rows and marks partial when a further page fails", async () => {
    const listAudit = vi
      .fn()
      .mockResolvedValueOnce(page([item()], "cursor-1"))
      .mockRejectedValueOnce(new ApiError("INTERNAL_ERROR", "boom", 500));
    const { wrapper } = await render(listAudit);

    const more = wrapper
      .findAll("button")
      .find((button) => button.text() === "載入更多");
    await more?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("載入下一頁時失敗");
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
  });

  it("reports the loaded count and never invents a total", async () => {
    const { wrapper } = await render(
      vi.fn().mockResolvedValue(page([item(), item()], "cursor-1")),
    );
    expect(wrapper.text()).toContain("已載入 2 筆");
    expect(wrapper.text()).not.toMatch(/共\s*\d+\s*筆|of\s+\d+/);
  });

  it("says it has reached the end instead of offering another page", async () => {
    const { wrapper } = await render(vi.fn().mockResolvedValue(page([item()])));
    expect(wrapper.text()).toContain("已到結尾");
    expect(
      wrapper.findAll("button").some((button) => button.text() === "載入更多"),
    ).toBe(false);
  });

  it("advances the cursor when loading more", async () => {
    const listAudit = vi
      .fn()
      .mockResolvedValueOnce(page([item()], "cursor-1"))
      .mockResolvedValueOnce(page([item({ id: "second" })]));
    const { wrapper } = await render(listAudit);

    await wrapper
      .findAll("button")
      .find((button) => button.text() === "載入更多")
      ?.trigger("click");
    await flushPromises();

    expect(listAudit.mock.calls[1][0].cursor).toBe("cursor-1");
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);
  });

  it("expands one row's metadata as JSON and collapses it again", async () => {
    const { wrapper } = await render(
      vi
        .fn()
        .mockResolvedValue(
          page([item({ metadata: { reason: "maintenance" } })]),
        ),
    );
    const toggle = wrapper
      .findAll("button")
      .find((button) => button.text() === "展開");
    expect(toggle?.attributes("aria-expanded")).toBe("false");

    await toggle?.trigger("click");
    expect(wrapper.find("pre").text()).toContain("maintenance");
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text() === "收合")
        ?.attributes("aria-expanded"),
    ).toBe("true");

    await wrapper
      .findAll("button")
      .find((button) => button.text() === "收合")
      ?.trigger("click");
    expect(wrapper.find("pre").exists()).toBe(false);
  });

  it("renders only the metadata the server returned", async () => {
    // The server strips banned keys; this asserts the view adds nothing back and
    // does not stringify the whole row into the panel.
    const { wrapper } = await render(
      vi.fn().mockResolvedValue(page([item({ metadata: { result: "ok" } })])),
    );
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "展開")
      ?.trigger("click");
    const shown = JSON.parse(wrapper.find("pre").text());
    expect(shown).toEqual({ result: "ok" });
  });

  it("applies the filter, reflects it in the URL and requests it", async () => {
    const listAudit = vi.fn().mockResolvedValue(page([item()]));
    const { wrapper, router } = await render(listAudit);

    const checkbox = wrapper.find('input[type="checkbox"]');
    await checkbox.setValue(true);
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const firstAction = ACTION_GROUPS[0].actions[0];
    expect(router.currentRoute.value.query.action).toBe(firstAction);
    expect(listAudit.mock.calls.at(-1)?.[0].action).toEqual([firstAction]);
  });

  it("restores the filter from the URL on load", async () => {
    // So a shared link, or a reload, shows the same question.
    const listAudit = vi.fn().mockResolvedValue(page([item()]));
    const { wrapper } = await render(listAudit, {
      action: "node.remove",
      range: "7d",
    });

    expect(listAudit.mock.calls[0][0].action).toEqual(["node.remove"]);
    const checked = wrapper
      .findAll('input[type="checkbox"]')
      .filter((input) => (input.element as HTMLInputElement).checked);
    expect(checked).toHaveLength(1);
    expect((wrapper.find("select").element as HTMLSelectElement).value).toBe(
      "7d",
    );
  });

  it("clear resets the filter and the URL", async () => {
    const listAudit = vi.fn().mockResolvedValue(page([item()]));
    const { wrapper, router } = await render(listAudit, {
      action: "node.remove",
    });

    await wrapper
      .findAll("button")
      .find((button) => button.text() === "Clear")
      ?.trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query.action).toBeUndefined();
    expect(listAudit.mock.calls.at(-1)?.[0].action).toBeUndefined();
  });

  it("reveals custom bounds only for the custom range", async () => {
    const { wrapper } = await render(vi.fn().mockResolvedValue(page([item()])));
    expect(wrapper.find('input[type="datetime-local"]').exists()).toBe(false);
    await wrapper.find("select").setValue("custom");
    expect(wrapper.findAll('input[type="datetime-local"]')).toHaveLength(2);
  });

  it("renders a row with no actor or resource without breaking", async () => {
    // Daemon- and system-initiated events have no actor; hiding them would
    // silently shorten the trail.
    const { wrapper } = await render(
      vi.fn().mockResolvedValue(
        page([
          item({
            actor: null,
            node: null,
            request_id: null,
            action: "node.register",
          }),
        ]),
      ),
    );
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    expect(wrapper.text()).toContain("Node 註冊");
  });

  it("names a resource whose id no longer resolves rather than hiding it", async () => {
    const { wrapper } = await render(
      vi.fn().mockResolvedValue(
        page([
          item({
            actor: { id: "gone", username: null, display_name: null },
            node: { id: "gone-node", name: null },
          }),
        ]),
      ),
    );
    expect(wrapper.text()).toContain("（已刪除）");
    expect(wrapper.text()).toContain("（已刪除的 Node）");
  });

  it("announces the result count for screen readers", async () => {
    const { wrapper } = await render(
      vi.fn().mockResolvedValue(page([item(), item()])),
    );
    const live = wrapper.find('[aria-live="polite"][role="status"]');
    expect(live.text()).toContain("已載入 2 筆");
  });

  it("gives the table a caption and column scopes", async () => {
    const { wrapper } = await render(vi.fn().mockResolvedValue(page([item()])));
    expect(wrapper.find("caption").exists()).toBe(true);
    expect(wrapper.findAll('th[scope="col"]').length).toBeGreaterThan(0);
  });

  it("labels the request-id copy control with the id it copies", async () => {
    const { wrapper } = await render(vi.fn().mockResolvedValue(page([item()])));
    const copy = wrapper
      .findAll("button")
      .find((button) => button.text() === "複製");
    expect(copy?.attributes("aria-label")).toContain("01K0REQUEST");
  });
});

describe("audit action vocabulary", () => {
  it("offers every server-side action in exactly one filter group", () => {
    // An action missing from the groups is unfilterable in the UI even though the
    // server accepts it; a duplicate would render two checkboxes for one value.
    expect(ungroupedActions()).toEqual([]);
    const grouped = ACTION_GROUPS.flatMap((group) => group.actions);
    expect(grouped.slice().sort()).toEqual([...AUDIT_ACTIONS].sort());
    expect(new Set(grouped).size).toBe(grouped.length);
  });
});
