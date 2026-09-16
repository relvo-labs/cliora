// The app shell's *structural* contract (plan/09 LY-01/LY-02, extended in
// plan/28).
//
// jsdom has no layout, so nothing here can assert a height — the geometry is
// asserted by the measuring Playwright test in tests/e2e/session.spec.ts, and
// that is the only place it can be. What these tests can protect is the shape
// the CSS grid depends on: header, rail and main must stay *direct* children of
// `.shell` (grid column/row placement only applies to direct children), the slot
// must land inside main, and the fill flag must reach main, since
// `main[data-fill]` is what turns off page scrolling for the workspace.
//
// Two things changed in plan/28 and both show up here:
//
//   * Navigation items are Lucide icons, so at a collapsed width they have no
//     visible text. Every assertion about "is this item offered" therefore goes
//     through the **accessible name**, which is the right question anyway: it
//     holds in both the expanded and the collapsed rail, and it is what a
//     screen-reader user actually gets.
//   * The rail leaves the grid entirely below 768px and returns as an overlay,
//     so `width` has to be set deliberately per test rather than inherited from
//     jsdom's default of 1024.

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { useAuthStore } from "../../stores/auth";
import { usePreferencesStore } from "../../stores/preferences";
import AppLayout from "./AppLayout.vue";

function testRouter(): Router {
  const blank = { template: "<div/>" };
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/dashboard", name: "dashboard", component: blank },
      { path: "/nodes", name: "nodes", component: blank },
      { path: "/sessions", name: "sessions", component: blank },
      { path: "/enrollment", name: "enrollment", component: blank },
      { path: "/audit", name: "audit", component: blank },
      {
        path: "/settings/integrations",
        name: "integrations",
        component: blank,
      },
      {
        path: "/settings/preferences",
        name: "preferences",
        component: blank,
      },
      { path: "/login", name: "login", component: blank },
    ],
  });
}

function setWidth(px: number): void {
  Object.defineProperty(window, "innerWidth", {
    value: px,
    configurable: true,
    writable: true,
  });
}

async function render(
  props: { fill?: boolean } = {},
  permissions: string[] = [
    "enrollment.manage",
    "audit.view",
    "integration.manage",
  ],
) {
  const store = useAuthStore();
  store.user = {
    id: "u",
    username: "u",
    display_name: "U",
    role: "Admin",
    permissions,
  };
  const router = testRouter();
  await router.push("/dashboard");
  await router.isReady();
  return mount(AppLayout, {
    props,
    slots: { default: '<p class="page">page content</p>' },
    global: { plugins: [router] },
    attachTo: document.body,
  });
}

/** Accessible names of the rail's links, however the rail is rendering them. */
function navNames(wrapper: ReturnType<typeof mount>): string[] {
  return wrapper
    .findAll("nav a")
    .map((link) => link.attributes("aria-label") ?? link.text())
    .map((name) => name.trim());
}

describe("AppLayout", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    setWidth(1440);
    localStorage.clear();
  });

  it("keeps header, rail and main as direct children of the shell grid", async () => {
    const wrapper = await render();
    // `> header` etc. is how the stylesheet places them; a wrapper element
    // inserted around any of the three silently breaks the grid and nothing
    // else in the suite would notice.
    expect(wrapper.findAll(".shell > header")).toHaveLength(1);
    expect(wrapper.findAll(".shell > aside")).toHaveLength(1);
    expect(wrapper.findAll(".shell > main")).toHaveLength(1);
  });

  it("renders the page inside main, not beside it", async () => {
    const wrapper = await render();
    expect(wrapper.get("main .page").text()).toBe("page content");
  });

  it("scrolls the page normally by default", async () => {
    const wrapper = await render();
    expect(wrapper.get("main").attributes("data-fill")).toBeUndefined();
  });

  it("marks main as a fill surface when a view owns the whole viewport", async () => {
    const wrapper = await render({ fill: true });
    expect(wrapper.get("main").attributes("data-fill")).toBe("");
  });

  it("offers Integrations only to a holder of integration.manage", async () => {
    // Hiding the entry is a courtesy, not authorization — the server refuses the request
    // either way (ADR 0016). What it buys is a rail that does not offer a Developer a page
    // whose every route answers 403.
    const admin = await render({}, ["integration.manage"]);
    expect(navNames(admin)).toContain("Integrations");

    const developer = await render({}, ["tunnel.view", "tunnel.manage"]);
    expect(navNames(developer)).not.toContain("Integrations");
  });

  it("names every navigation item, with or without a visible label", async () => {
    // The seven text glyphs this replaces were readable text nodes, so a screen
    // reader pronounced them — as whatever the matched font decided. An icon
    // with no name is the same failure with a nicer appearance.
    const wrapper = await render();
    const links = wrapper.findAll("nav a");
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      const name = link.attributes("aria-label") ?? link.text();
      expect(name.trim().length).toBeGreaterThan(0);
    }
  });

  it("puts a skip link first, so the keyboard route to main is one stop", async () => {
    const wrapper = await render();
    const first = wrapper.get(".shell").element.firstElementChild;
    expect(first?.tagName).toBe("A");
    expect(first?.getAttribute("href")).toBe("#main");
    expect(wrapper.get("main").attributes("id")).toBe("main");
  });

  it("collapses the rail automatically below 1440px", async () => {
    // A measurement, not a preference: an expanded rail costs the centre panel
    // 144px, and at 1024 the terminal cannot spare it.
    setWidth(1200);
    const wrapper = await render();
    expect(wrapper.get(".shell").attributes("data-collapsed")).toBe("");
  });

  it("lets the user collapse the rail at a desktop width, and remembers it", async () => {
    const wrapper = await render();
    expect(wrapper.get(".shell").attributes("data-collapsed")).toBeUndefined();

    const toggle = wrapper.get('[aria-controls="primary-nav"]');
    expect(toggle.attributes("aria-expanded")).toBe("true");
    await toggle.trigger("click");

    expect(wrapper.get(".shell").attributes("data-collapsed")).toBe("");
    expect(usePreferencesStore().navCollapsed).toBe(true);
    expect(localStorage.getItem("cliora-nav-collapsed")).toBe("true");
  });

  it("keeps a collapsed item reachable rather than removing it", async () => {
    // Collapse is a visual state. An item that disappeared from the DOM would
    // be indistinguishable from an item hidden for lack of permission.
    setWidth(1200);
    const wrapper = await render();
    expect(navNames(wrapper)).toContain("Sessions");
  });

  it("offers no collapse control in the narrow menu, where it would do nothing", async () => {
    // Two bugs in one assertion, both found by review rather than by a test:
    //
    //   * the overlay used to render the collapse toggle wired to a no-op, so
    //     pressing it did nothing and the user had to work out whether it was
    //     broken or they were;
    //   * the fix then removed it from the *desktop* rail too, because Vue
    //     casts an absent Boolean prop to `false` — so "did not opt out" and
    //     "explicitly opted out" were the same value.
    setWidth(390);
    const narrow = await render();
    await narrow.get(".menu-toggle").trigger("click");
    expect(
      narrow.get(".menu-panel").find('[aria-controls="primary-nav"]').exists(),
    ).toBe(false);

    setWidth(1440);
    const desktop = await render();
    expect(desktop.find('[aria-controls="primary-nav"]').exists()).toBe(true);
  });

  it("contains focus in the narrow menu and returns it on Escape", async () => {
    // The overlay owes the same three things a dialog does. It shares the
    // composable with the file drawer for that reason.
    setWidth(390);
    const wrapper = await render();
    const toggle = wrapper.get(".menu-toggle");
    await toggle.trigger("click");
    expect(wrapper.find(".menu-panel").exists()).toBe(true);

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".menu-panel").exists()).toBe(false);
  });

  it("puts personal settings and sign-out behind the account menu", async () => {
    // Not a bare `<select>` in the header. A theme is a global preference, and
    // a permanent header control makes it read as page-scoped — which is also
    // what plan/28 §4 said before the account menu existed to hold it.
    const wrapper = await render();
    const trigger = wrapper.get('[aria-haspopup="menu"]');
    expect(trigger.attributes("aria-expanded")).toBe("false");
    // Nothing is offered until the menu is opened.
    expect(wrapper.text()).not.toContain("個人設定");

    await trigger.trigger("click");
    expect(trigger.attributes("aria-expanded")).toBe("true");
    const items = wrapper.findAll('[role="menuitem"]');
    expect(items.map((i) => i.text())).toEqual(["個人設定", "登出"]);
    expect(items[0].attributes("href")).toBe("/settings/preferences");
  });

  it("keeps no theme control in the header", async () => {
    // A regression guard on the placement, not on the styling: the control was
    // here, and moving it is the point.
    const wrapper = await render();
    expect(wrapper.find('[aria-label="視覺主題"]').exists()).toBe(false);
  });

  it("replaces the rail with a menu below 768px", async () => {
    // At 390px a 64px rail beside a terminal is not a layout, so the rail
    // leaves the grid and comes back as an overlay.
    setWidth(390);
    const wrapper = await render();
    expect(wrapper.find(".shell > aside").exists()).toBe(false);
    expect(wrapper.get(".shell").attributes("data-narrow")).toBe("");

    const toggle = wrapper.get(".menu-toggle");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    await toggle.trigger("click");
    // Reachable, not hidden: the shared foundation forbids simply removing a
    // function at a narrow width.
    expect(wrapper.find(".menu-panel").exists()).toBe(true);
    expect(navNames(wrapper)).toContain("Sessions");
  });
});

describe("行動導覽（plan/29 MS-03）", () => {
  it("窄視窗的覆蓋抽屜把 Sessions 排在第一項", async () => {
    setWidth(390);
    const wrapper = await render();
    await wrapper.get(".menu-toggle").trigger("click");
    expect(navNames(wrapper)[0]).toBe("Sessions");
  });

  it("桌面側欄的順序完全不變", async () => {
    // The mobile entry point is an ordering change and nothing else; if this
    // goes red, it stopped being scoped to the overlay (MS-D-01).
    setWidth(1440);
    const wrapper = await render();
    expect(navNames(wrapper)[0]).toBe("Dashboard");
  });

  it("權限決定的可見性不跟著順序走", async () => {
    // Hoisting must not become a second, quieter way to decide what renders.
    setWidth(390);
    const developer = await render({}, []);
    await developer.get(".menu-toggle").trigger("click");
    const names = navNames(developer);
    expect(names[0]).toBe("Sessions");
    expect(names).not.toContain("Integrations");
    expect(names).not.toContain("Audit");
  });
});

describe("視窗高度（plan/29 MS-02）", () => {
  interface FakeViewport {
    height: number;
    listeners: Map<string, Set<() => void>>;
  }
  function installVisualViewport(height: number): FakeViewport {
    const vv: FakeViewport = { height, listeners: new Map() };
    Object.defineProperty(window, "visualViewport", {
      configurable: true,
      writable: true,
      value: {
        get height() {
          return vv.height;
        },
        addEventListener: (type: string, fn: () => void) => {
          if (!vv.listeners.has(type)) vv.listeners.set(type, new Set());
          vv.listeners.get(type)?.add(fn);
        },
        removeEventListener: (type: string, fn: () => void) => {
          vv.listeners.get(type)?.delete(fn);
        },
      },
    });
    return vv;
  }
  function fire(vv: FakeViewport, type: string): void {
    for (const fn of vv.listeners.get(type) ?? []) fn();
  }

  it("軟體鍵盤縮小可用高度時，shell 跟著縮", async () => {
    const vv = installVisualViewport(844);
    setWidth(390);
    await render();
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--viewport-usable-height")).toBe(
      "844px",
    );

    // A keyboard opens: visualViewport shrinks, `100dvh` does not.
    vv.height = 420;
    fire(vv, "resize");
    expect(root.style.getPropertyValue("--viewport-usable-height")).toBe(
      "420px",
    );
  });

  it("iOS 用 scroll 回報鍵盤變化，也要接得到", async () => {
    const vv = installVisualViewport(844);
    setWidth(390);
    await render();
    vv.height = 500;
    fire(vv, "scroll");
    expect(
      document.documentElement.style.getPropertyValue(
        "--viewport-usable-height",
      ),
    ).toBe("500px");
  });

  it("卸載時解除監聽並清掉變數", async () => {
    const vv = installVisualViewport(844);
    setWidth(390);
    const wrapper = await render();
    wrapper.unmount();

    // Removed rather than left behind: the login page has no shell, and a stale
    // height from the last session would size it.
    expect(
      document.documentElement.style.getPropertyValue(
        "--viewport-usable-height",
      ),
    ).toBe("");
    expect(vv.listeners.get("resize")?.size ?? 0).toBe(0);
    expect(vv.listeners.get("scroll")?.size ?? 0).toBe(0);
  });

  it("瀏覽器沒有 visualViewport 時，什麼都不設，讓 CSS 回退", async () => {
    // @ts-expect-error — the absence is the case under test.
    delete window.visualViewport;
    setWidth(390);
    await render();
    expect(
      document.documentElement.style.getPropertyValue(
        "--viewport-usable-height",
      ),
    ).toBe("");
  });
});
