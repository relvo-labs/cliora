// The app shell's *structural* contract (plan/09 LY-01/LY-02).
//
// jsdom has no layout, so nothing here can assert a height — the geometry is
// asserted by the measuring Playwright test in tests/e2e/session.spec.ts, and
// that is the only place it can be. What these tests can protect is the shape
// the CSS grid depends on: header, rail and main must stay *direct* children of
// `.shell` (grid column/row placement only applies to direct children), the slot
// must land inside main, and the fill flag must reach main, since
// `main[data-fill]` is what turns off page scrolling for the workspace.

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { useAuthStore } from "../../stores/auth";
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
      { path: "/login", name: "login", component: blank },
    ],
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
  });
}

describe("AppLayout", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
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
    expect(admin.get("nav").text()).toContain("Integrations");

    const developer = await render({}, ["tunnel.view", "tunnel.manage"]);
    expect(developer.get("nav").text()).not.toContain("Integrations");
  });
});
