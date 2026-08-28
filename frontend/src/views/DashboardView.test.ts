// The nine UI states and the freshness presentation (P4-08, style §23).
//
// Most of these assert a *refusal*: no number where one could not be read, no zero where
// nothing reported, no skeleton over rendered data, no automatic polling. Those are the
// properties the whole freshness contract exists for, and each is easy to undo by
// accident.

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { ApiError } from "../api/client";
import { useAuthStore } from "../stores/auth";
import * as auth from "../stores/auth";
import { useDashboardStore } from "../stores/dashboard";
import {
  summaryFixture,
  unhealthyNode,
  type FixtureOptions,
} from "../testing/dashboardFixture";
import DashboardView from "./DashboardView.vue";

function testRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/dashboard", name: "dashboard", component: DashboardView },
      { path: "/nodes", name: "nodes", component: { template: "<div/>" } },
      {
        path: "/nodes/:id",
        name: "node-detail",
        component: { template: "<div/>" },
      },
      { path: "/audit", name: "audit", component: { template: "<div/>" } },
      {
        path: "/enrollment",
        name: "enrollment",
        component: { template: "<div/>" },
      },
    ],
  });
}

function signIn(permissions: string[]): void {
  const store = useAuthStore();
  store.user = {
    id: "u",
    username: "u",
    display_name: "U",
    role: "Admin",
    permissions,
    features: [],
  };
}

async function render(
  options: {
    fixture?: FixtureOptions;
    getSummary?: ReturnType<typeof vi.fn>;
    permissions?: string[];
  } = {},
) {
  signIn(
    options.permissions ?? ["node.view", "enrollment.manage", "audit.view"],
  );
  const getSummary =
    options.getSummary ??
    vi.fn().mockResolvedValue(summaryFixture(options.fixture ?? {}));
  vi.spyOn(auth, "api").mockReturnValue({
    getDashboardSummary: getSummary,
  } as unknown as ReturnType<typeof auth.api>);

  const router = testRouter();
  await router.push("/dashboard");
  await router.isReady();
  const wrapper = mount(DashboardView, {
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return { wrapper, router, getSummary };
}

describe("DashboardView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    // Fake timers for the whole suite: the freshness badge computes an age from `now`
    // minus the server's fetch time, so a fixed clock makes "10 seconds ago"
    // deterministic — and the polling tests need to advance the same clock. Mixing real
    // and fake timers per test is what made the first version of this file fail.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-25T12:00:00Z"));
  });

  afterEach(() => {
    useDashboardStore().detach();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  // --- success ---

  it("shows the PRD §10.2 figures", async () => {
    const { wrapper } = await render();
    const text = wrapper.text();
    expect(text).toContain("線上 Node");
    expect(text).toContain("離線 Node");
    expect(text).toContain("執行中 Session");
    expect(text).toContain("Claude Session");
    expect(text).toContain("Codex Session");
    expect(text).toContain("最近活動");
    expect(text).toContain("異常 Node");
  });

  it("gives each big number an accessible name", async () => {
    // A screen reader reaching a bare "2" out of its visual context learns nothing.
    //
    // **Asserted as rendered text, not as an `aria-label` attribute.** This test used to
    // look for `[aria-label]` and passed for months while the feature did not work: the
    // label sat on a `<p>`, ARIA prohibits `aria-label` on a `<p>` with no role, and the
    // accessibility tree discarded it — so the reader heard "2". `HD-04`'s axe scan
    // reported it eight times on this page.
    //
    // The lesson is about the assertion, not the markup: **checking that an attribute is
    // present is not checking that it does anything.** The text is now in a `.sr-only`
    // span, which is in the tree by construction, and this reads the span.
    const { wrapper } = await render();
    expect(wrapper.text()).toContain("線上 Node：2");
    // And the visual number stays hidden from the tree, or the reader hears it twice.
    expect(
      wrapper.findAll('.value span[aria-hidden="true"]').length,
    ).toBeGreaterThan(0);
  });

  it("shows each block's age relative to when the server fetched it", async () => {
    // Not "now": the server's `generated_at` is deliberately a few seconds old on a
    // cache hit, and showing that is the contract working.
    const { wrapper } = await render();
    expect(wrapper.text()).toContain("10 秒前");
  });

  // --- loading ---

  it("shows a skeleton only before the first response", async () => {
    const { wrapper } = await render({
      getSummary: vi.fn().mockReturnValue(new Promise(() => {})),
    });
    expect(wrapper.text()).toContain("正在載入");
    expect(wrapper.text()).not.toContain("線上 Node");
  });

  it("keeps the numbers on screen during a refresh", async () => {
    // A skeleton over rendered data every 30 s would manufacture activity.
    const { wrapper } = await render();
    const refresh = wrapper
      .findAll("button")
      .find((button) => button.text().includes("重新整理"));
    await refresh?.trigger("click");
    expect(wrapper.text()).toContain("線上 Node");
    expect(wrapper.text()).not.toContain("正在載入");
  });

  // --- empty / offline ---

  it("offers the enrollment link on an empty deployment", async () => {
    const { wrapper } = await render({
      fixture: {
        nodes: { online: 0, degraded: 0, offline: 0, disabled: 0, total: 0 },
      },
    });
    expect(wrapper.text()).toContain("尚未安裝任何 Node");
    expect(wrapper.text()).toContain("建立安裝 Token");
  });

  it("tells a non-Admin who to ask instead of linking enrollment", async () => {
    // Hiding the link without saying why leaves a dead end, so the text still names the
    // next step — what must be absent is the link they cannot use.
    const { wrapper } = await render({
      permissions: ["node.view"],
      fixture: {
        nodes: { online: 0, degraded: 0, offline: 0, disabled: 0, total: 0 },
      },
    });
    expect(wrapper.text()).toContain("請聯繫 Admin");
    expect(wrapper.find('a[href="/enrollment"]').exists()).toBe(false);
  });

  it("links enrollment for a role that can use it", async () => {
    const { wrapper } = await render({
      fixture: {
        nodes: { online: 0, degraded: 0, offline: 0, disabled: 0, total: 0 },
      },
    });
    expect(wrapper.find('a[href="/enrollment"]').exists()).toBe(true);
  });

  it("distinguishes an offline fleet from an empty deployment", async () => {
    const { wrapper } = await render({
      fixture: {
        nodes: { online: 0, degraded: 0, offline: 3, disabled: 0, total: 3 },
      },
    });
    const text = wrapper.text();
    expect(text).toContain("所有 Node 都不在線");
    expect(text).toContain("runbook");
    expect(text).not.toContain("尚未安裝任何 Node");
  });

  // --- stale ---

  it("keeps a stale block's numbers and marks them as possibly outdated", async () => {
    // Hiding them would be a different lie: the data is real, just older than the
    // contract lets it pass as current.
    const { wrapper } = await render({ fixture: { stale: ["nodes"] } });
    const text = wrapper.text();
    expect(text).toContain("2"); // the online count is still shown
    expect(text).toContain("可能過時");
    expect(text).toContain("數字仍顯示，但可能不是最新狀態");
  });

  it("marks stale in words, not only in colour", async () => {
    const { wrapper } = await render({ fixture: { stale: ["nodes"] } });
    const badge = wrapper.find('[data-status="stale"]');
    expect(badge.exists()).toBe(true);
    // A glyph and a word, so it survives greyscale and colour blindness (WCAG 1.4.1).
    expect(badge.text()).toContain("可能過時");
  });

  // --- partial (degraded block) ---

  it("degrades one card and leaves the others showing real numbers", async () => {
    const { wrapper } = await render({ fixture: { degraded: ["resources"] } });
    const text = wrapper.text();
    expect(text).toContain("暫時無法取得");
    expect(text).toContain("BLOCK_UNAVAILABLE");
    // The nodes block is untouched.
    expect(text).toContain("線上 Node");
    expect(wrapper.findAll('[data-status="degraded"]').length).toBeGreaterThan(
      0,
    );
  });

  it("says once, at the top, that the page is incomplete", async () => {
    const { wrapper } = await render({ fixture: { degraded: ["resources"] } });
    expect(wrapper.text()).toContain("個區塊暫時無法取得");
  });

  it("shows no number at all for a degraded block", async () => {
    // Rendering 0 for a figure that could not be read would be a fabrication.
    const { wrapper } = await render({ fixture: { degraded: ["sessions"] } });
    const card = wrapper
      .findAll("section")
      .find((section) => section.text().includes("執行中 Session"));
    expect(card?.find(".value").exists()).toBe(false);
    expect(card?.text()).toContain("暫時無法取得");
  });

  it("offers a retry on a degraded card", async () => {
    const { wrapper, getSummary } = await render({
      fixture: { degraded: ["resources"] },
    });
    const retry = wrapper
      .findAll("button")
      .find((button) => button.text() === "重試");
    await retry?.trigger("click");
    await flushPromises();
    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  // --- no data vs zero ---

  it("shows no-data rather than 0% for a measurement nothing reported", async () => {
    // 0% CPU and "no node has reported" are different facts.
    const { wrapper } = await render();
    const card = wrapper
      .findAll("section")
      .find((section) => section.text().includes("CPU（fleet 平均）"));
    expect(card?.text()).toContain("尚無資料");
    expect(card?.text()).not.toContain("0%");
  });

  it("shows a measurement that was reported, with how many nodes reported it", async () => {
    const { wrapper } = await render({
      fixture: { measurements: { cpu_usage: { average: 42.5, nodes: 2 } } },
    });
    const card = wrapper
      .findAll("section")
      .find((section) => section.text().includes("CPU（fleet 平均）"));
    expect(card?.text()).toContain("42.5");
    expect(card?.text()).toContain("2 個 Node 回報");
  });

  it("shows a genuine zero as zero", async () => {
    // The counterpart of the rule above: a real 0 must not be turned into "no data".
    const { wrapper } = await render({
      fixture: { perRuntime: { claude: 0 } },
    });
    const card = wrapper
      .findAll("section")
      .find((section) => section.text().includes("Codex Session"));
    expect(card?.text()).toContain("0");
    expect(card?.text()).not.toContain("尚無資料");
  });

  // --- forbidden / error ---

  it("shows a forbidden state without the cards", async () => {
    const { wrapper } = await render({
      getSummary: vi
        .fn()
        .mockRejectedValue(new ApiError("FORBIDDEN", "no", 403)),
    });
    expect(wrapper.text()).toContain("沒有檢視 Dashboard 的權限");
    expect(wrapper.text()).not.toContain("線上 Node");
  });

  it("shows the error catalog's guidance and a retry on failure", async () => {
    const { wrapper } = await render({
      getSummary: vi
        .fn()
        .mockRejectedValue(
          new ApiError("INTERNAL_ERROR", "boom", 500, "rid-3"),
        ),
    });
    const text = wrapper.text();
    expect(text).toContain("rid-3");
    expect(text).toContain("下一步");
  });

  it("keeps the numbers and explains when a refresh fails", async () => {
    const getSummary = vi
      .fn()
      .mockResolvedValueOnce(summaryFixture())
      .mockRejectedValueOnce(new ApiError("INTERNAL_ERROR", "boom", 500));
    const { wrapper } = await render({ getSummary });

    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("重新整理"))
      ?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("最近一次更新失敗");
    expect(wrapper.text()).toContain("線上 Node");
  });

  // --- unhealthy nodes ---

  it("states a reason for each unhealthy node", async () => {
    // A list of names tells an operator nothing they did not already suspect.
    const { wrapper } = await render({
      fixture: {
        unhealthy: [
          unhealthyNode({
            reasons: ["offline_but_enabled", "no_runtime_available"],
          }),
        ],
      },
    });
    const text = wrapper.text();
    expect(text).toContain("broken-01");
    expect(text).toContain("已啟用但沒有連線");
    expect(text).toContain("沒有任何可用的 runtime");
  });

  it("is honest when the unhealthy list is truncated", async () => {
    const { wrapper } = await render({
      fixture: { unhealthy: [unhealthyNode()], unhealthyTotal: 37 },
    });
    expect(wrapper.text()).toContain("共 37 筆異常");
  });

  it("opens a node from the unhealthy list", async () => {
    const { wrapper, router } = await render({
      fixture: { unhealthy: [unhealthyNode({ id: "n-42" })] },
    });
    await wrapper
      .findAll("button")
      .find((button) => button.text() === "broken-01")
      ?.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.params.id).toBe("n-42");
  });

  it("says so plainly when nothing is unhealthy", async () => {
    const { wrapper } = await render();
    expect(wrapper.text()).toContain("目前沒有異常的 Node");
  });

  // --- role differences ---

  it("explains hidden actors rather than showing bare dashes", async () => {
    // A column of dashes with no explanation reads as "these events had no actor".
    const { wrapper } = await render({
      permissions: ["node.view"],
      fixture: { actorsHidden: true },
    });
    expect(wrapper.text()).toContain("只有 Admin 能看到執行者");
    expect(wrapper.text()).not.toContain("Alice");
  });

  it("shows actors and the audit link to an Admin", async () => {
    const { wrapper } = await render();
    expect(wrapper.text()).toContain("Alice");
    expect(wrapper.text()).toContain("查看完整 Audit Log");
  });

  it("hides the audit link from a role that cannot use it", async () => {
    const { wrapper } = await render({ permissions: ["node.view"] });
    expect(wrapper.text()).not.toContain("查看完整 Audit Log");
  });

  // --- a11y and polling ---

  it("does not poll until the user opts in", async () => {
    const { getSummary } = await render();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(getSummary).toHaveBeenCalledTimes(1);
  });

  it("polls once the toggle is on", async () => {
    const { wrapper, getSummary } = await render();
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(getSummary).toHaveBeenCalledTimes(2);
  });

  it("announces the state for screen readers", async () => {
    const { wrapper } = await render({ fixture: { degraded: ["resources"] } });
    const live = wrapper.find('[aria-live="polite"][role="status"]');
    expect(live.text()).toContain("Dashboard 已更新");
    expect(live.text()).toContain("1 個區塊無法取得");
  });

  it("respects prefers-reduced-motion", async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) =>
      ({
        matches: query.includes("prefers-reduced-motion"),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList) as typeof window.matchMedia;
    try {
      const { wrapper } = await render();
      expect(wrapper.find('[data-reduced-motion="true"]').exists()).toBe(true);
    } finally {
      window.matchMedia = original;
    }
  });

  it("stops its timer when the page is left", async () => {
    // Otherwise a background dashboard keeps requesting forever.
    const { wrapper, getSummary } = await render();
    const store = useDashboardStore();
    store.setAutoRefresh(true);
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(getSummary).toHaveBeenCalledTimes(1);
  });
});
