// Personal settings (plan/28 VR-10).
//
// The interesting assertion here is the third state. A theme has three, not
// two: graphite, porcelain, and "whatever the OS says". The control this
// replaced was a two-option `<select>`, so once a user picked anything they
// could never hand the decision back to their operating system — the stored key
// was written and never removed. That is the bug these tests pin.

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { useAuthStore } from "../stores/auth";
import { usePreferencesStore } from "../stores/preferences";
import PreferencesView from "./PreferencesView.vue";

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
      { path: "/settings/preferences", name: "preferences", component: blank },
      { path: "/login", name: "login", component: blank },
    ],
  });
}

/** jsdom has no matchMedia; the store and the view both ask about the OS. */
function stubPrefersLight(light: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: query.includes("light") ? light : !light,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
      onchange: null,
    }),
  });
}

async function render() {
  const auth = useAuthStore();
  auth.user = {
    id: "u",
    username: "u",
    display_name: "U",
    role: "Viewer",
    permissions: [],
  };
  const router = testRouter();
  await router.push("/settings/preferences");
  await router.isReady();
  return mount(PreferencesView, { global: { plugins: [router] } });
}

describe("PreferencesView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    stubPrefersLight(false);
    document.documentElement.removeAttribute("data-theme");
  });

  it("offers follow-the-system as well as the two shipped themes", async () => {
    const wrapper = await render();
    const radios = wrapper.findAll('input[name="theme"]');
    expect(radios).toHaveLength(3);
    expect(wrapper.text()).toContain("跟隨系統");
    expect(wrapper.text()).toContain("石墨");
    expect(wrapper.text()).toContain("明亮");
  });

  it("starts on follow-the-system when nothing was ever chosen", async () => {
    const wrapper = await render();
    const radios = wrapper.findAll('input[name="theme"]');
    expect((radios[0].element as HTMLInputElement).checked).toBe(true);
    expect(usePreferencesStore().themeIsExplicit).toBe(false);
  });

  it("records an explicit choice and applies it", async () => {
    const wrapper = await render();
    await wrapper.findAll('input[name="theme"]')[1].trigger("change");

    const preferences = usePreferencesStore();
    expect(preferences.theme).toBe("graphite");
    expect(preferences.themeIsExplicit).toBe(true);
    expect(localStorage.getItem("cliora-theme")).toBe("graphite");
    expect(document.documentElement.getAttribute("data-theme")).toBe(
      "graphite",
    );
  });

  it("can hand the decision back to the operating system", async () => {
    // The state that had no way out. Choosing porcelain on a dark OS and then
    // choosing "follow the system" must remove the key, not write another
    // value — otherwise the app keeps ignoring the OS forever.
    const wrapper = await render();
    await wrapper.findAll('input[name="theme"]')[2].trigger("change");
    expect(localStorage.getItem("cliora-theme")).toBe("porcelain");

    await wrapper.findAll('input[name="theme"]')[0].trigger("change");
    const preferences = usePreferencesStore();
    expect(localStorage.getItem("cliora-theme")).toBeNull();
    expect(preferences.themeIsExplicit).toBe(false);
    // The OS is dark in this test, so the effective theme follows it back.
    expect(preferences.theme).toBe("graphite");
    expect(document.documentElement.getAttribute("data-theme")).toBe(
      "graphite",
    );
  });

  it("says what the operating system currently prefers", async () => {
    // "Follow the system" is useless without saying what the system says.
    stubPrefersLight(true);
    const wrapper = await render();
    expect(wrapper.text()).toContain("淺色");
  });

  it("keeps the terminal font size and panel width inside their bounds", async () => {
    const wrapper = await render();
    const preferences = usePreferencesStore();
    const [font, width] = wrapper.findAll('input[type="range"]');

    (font.element as HTMLInputElement).value = "99";
    await font.trigger("input");
    expect(preferences.terminalFontSize).toBe(20);

    (width.element as HTMLInputElement).value = "9999";
    await width.trigger("input");
    expect(preferences.inspectorWidth).toBe(360);
  });

  it("states that preferences do not follow the user to another machine", async () => {
    // The one thing about these settings that surprises people, on the page
    // rather than only in a release note.
    const wrapper = await render();
    expect(wrapper.text()).toContain("設定不會跟著走");
    expect(wrapper.text()).toContain("目前沒有跨裝置同步");
  });

  it("says which themes were not verified, and why they are absent", async () => {
    const wrapper = await render();
    expect(wrapper.text()).toContain("經過驗收的是上面兩款");
  });

  it("restores every preference to its default", async () => {
    const wrapper = await render();
    const preferences = usePreferencesStore();
    preferences.setTheme("porcelain");
    preferences.setTerminalFontSize(19);
    preferences.setInspectorWidth(350);
    preferences.setNavCollapsed(true);

    const reset = wrapper
      .findAll("button")
      .find((b) => b.text().includes("回復預設設定"));
    expect(reset, "the reset button was not found").toBeDefined();
    await reset!.trigger("click");

    expect(preferences.themeIsExplicit).toBe(false);
    expect(preferences.terminalFontSize).toBe(14);
    expect(preferences.inspectorWidth).toBe(258);
    expect(preferences.navCollapsed).toBe(false);
  });
});

describe("cross-tab preference sync", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    stubPrefersLight(false);
    document.documentElement.removeAttribute("data-theme");
  });

  it("mirrors a theme chosen in another tab, without a reload", async () => {
    // Load-bearing, not a nicety. Personal settings is its own page, so
    // changing a theme means leaving whatever you were looking at — and leaving
    // the session workspace unmounts the terminal. Without this listener there
    // is no path at all through which a theme changes while a terminal is
    // alive, so the phase's central mechanism (recolour in place, never
    // `new Terminal()`) would be unreachable in the product.
    const { installPreferencesStorageSync } = await import(
      "../stores/preferences"
    );
    const stop = installPreferencesStorageSync();
    const preferences = usePreferencesStore();
    expect(preferences.themeIsExplicit).toBe(false);

    // What another tab writing the key looks like from here.
    localStorage.setItem("cliora-theme", "porcelain");
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "cliora-theme",
        newValue: "porcelain",
      }),
    );

    expect(preferences.theme).toBe("porcelain");
    expect(preferences.themeIsExplicit).toBe(true);
    expect(document.documentElement.getAttribute("data-theme")).toBe(
      "porcelain",
    );
    stop();
  });

  it("mirrors a return to following the system", async () => {
    const { installPreferencesStorageSync } = await import(
      "../stores/preferences"
    );
    const stop = installPreferencesStorageSync();
    const preferences = usePreferencesStore();
    preferences.setTheme("porcelain");

    localStorage.removeItem("cliora-theme");
    window.dispatchEvent(
      new StorageEvent("storage", { key: "cliora-theme", newValue: null }),
    );

    expect(preferences.themeIsExplicit).toBe(false);
    // The OS is dark in this test.
    expect(preferences.theme).toBe("graphite");
    stop();
  });

  it("ignores keys that are not ours", async () => {
    const { installPreferencesStorageSync } = await import(
      "../stores/preferences"
    );
    const stop = installPreferencesStorageSync();
    const preferences = usePreferencesStore();
    preferences.setTerminalFontSize(18);

    window.dispatchEvent(
      new StorageEvent("storage", { key: "something-else", newValue: "x" }),
    );

    expect(preferences.terminalFontSize).toBe(18);
    stop();
  });

  it("stops listening when torn down", async () => {
    const { installPreferencesStorageSync } = await import(
      "../stores/preferences"
    );
    const stop = installPreferencesStorageSync();
    stop();
    const preferences = usePreferencesStore();

    localStorage.setItem("cliora-theme", "porcelain");
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "cliora-theme",
        newValue: "porcelain",
      }),
    );

    expect(preferences.themeIsExplicit).toBe(false);
  });
});
