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
      { path: "/projects", name: "projects", component: blank },
      { path: "/nodes", name: "nodes", component: blank },
      { path: "/sessions", name: "sessions", component: blank },
      { path: "/my-work", name: "my-work", component: blank },
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
    "project.view",
  ],
  features: string[] = ["projects"],
) {
  const store = useAuthStore();
  store.user = {
    id: "u",
    username: "u",
    display_name: "U",
    role: "Admin",
    permissions,
    features,
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

// --- V2.0 navigation regrouping (plan/16 PJ-06, ADR 0027) ---
//
// The claim being defended is narrow and specific: **this is a regrouping, not a
// move.** Everything else here follows from that.

describe("AppLayout navigation groups", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  const ALL = [
    "enrollment.manage",
    "audit.view",
    "integration.manage",
    "project.view",
  ];

  function hrefs(wrapper: ReturnType<typeof mount>): string[] {
    return wrapper.findAll("nav a").map((a) => a.attributes("href") ?? "");
  }

  it("keeps every existing route path identical whether or not the layer is on", async () => {
    // The one assertion that would catch a regrouping turning into a move. Paths
    // are what bookmarks and the e2e suite hold; the grouping is presentation.
    const on = await render({}, ALL, ["projects"]);
    const off = await render({}, ALL, []);
    const existing = [
      "/dashboard",
      "/nodes",
      "/sessions",
      "/enrollment",
      "/audit",
      "/settings/integrations",
    ];
    for (const path of existing) {
      expect(hrefs(on)).toContain(path);
      expect(hrefs(off)).toContain(path);
    }
  });

  it("renders no group heading at all when the feature is off", async () => {
    // Flag off must be the *original* flat rail, not "the new rail minus one
    // entry" — that is what the screenshot baseline compares against.
    const wrapper = await render({}, ALL, []);
    expect(wrapper.findAll("[data-nav-group]")).toHaveLength(0);
    // Order included: "the regrouped rail minus one row" is a different picture
    // from "the rail as it was", and the screenshot baseline is the latter.
    expect(hrefs(wrapper)).toEqual([
      "/dashboard",
      "/nodes",
      "/sessions",
      "/enrollment",
      "/audit",
      "/settings/integrations",
    ]);
  });

  it("shows Projects and two group headings when the feature is on", async () => {
    const wrapper = await render({}, ALL, ["projects"]);
    expect(hrefs(wrapper)).toContain("/projects");
    // Two, not five: `Home`, `My Work`, `Projects`, `Agents` and `Sessions` are
    // single-entry groups and collapse to plain rows rather than repeating themselves as
    // a heading. `Infrastructure` and `Administration` are genuinely two levels — and
    // they are two rather than one because "which machines are up" and "who may join the
    // fleet" are different people's routines (PX-63).
    const groups = wrapper.findAll("[data-nav-group]");
    expect(groups.map((group) => group.text())).toEqual([
      "Infrastructure",
      "Administration",
    ]);
  });

  it("puts My Work first among the work entries (PX-63)", async () => {
    // The order is the order of a day rather than of the org chart: "what is waiting for
    // me" is the question somebody opens this application to answer.
    const wrapper = await render({}, ALL, ["projects"]);
    const links = hrefs(wrapper);
    expect(links.slice(0, 3)).toEqual(["/dashboard", "/my-work", "/projects"]);
  });

  it("calls the dashboard Home once the project layer is on", async () => {
    // A rename, not a rewrite: the fleet health block on it is pixel-identical to the one
    // on Dashboard, because that block is what V1 operators use every day.
    const wrapper = await render({}, ALL, ["projects"]);
    expect(wrapper.text()).toContain("Home");
    // And **not** renamed on the flag-off rail, which must stay the pre-V2 picture.
    const legacy = await render({}, ALL, []);
    expect(legacy.text()).toContain("Dashboard");
    expect(legacy.text()).not.toContain("My Work");
  });

  it("hides Projects when the deployment has it but the person may not see it", async () => {
    // `features` AND `permissions`. Either alone would be the wrong rule, and
    // neither is authorization — the server refuses regardless.
    const wrapper = await render({}, ["audit.view"], ["projects"]);
    expect(hrefs(wrapper)).not.toContain("/projects");
  });

  it("hides Projects when the person may see it but the deployment has no such thing", async () => {
    const wrapper = await render({}, ALL, []);
    expect(hrefs(wrapper)).not.toContain("/projects");
  });

  it("still groups when a Viewer sees only two infrastructure entries", async () => {
    // Viewer holds project.view but neither enrollment nor audit, so the group has
    // two children. An empty-looking group would be worse than none, so this pins
    // the case that decides it.
    const wrapper = await render({}, ["project.view"], ["projects"]);
    expect(hrefs(wrapper)).toEqual([
      "/dashboard",
      "/my-work",
      "/projects",
      "/sessions",
      "/nodes",
    ]);
    // One heading, not two: this reader holds neither `audit.view` nor enrollment, so
    // `Administration` has no children — and an empty-looking group is worse than none.
    const groups = wrapper.findAll("[data-nav-group]");
    expect(groups.map((group) => group.text())).toEqual(["Infrastructure"]);
  });
});
