// The project detail view's two load-bearing displays (plan/16 PJ-06 §9).
//
// Both exist because getting them subtly wrong is silent:
//
//   * a binding that cannot be used must say *why*, and the four reasons are not
//     interchangeable — "the machine is down" and "this machine no longer allows
//     this directory" call for different actions from the user;
//   * a missing actor means one of two different things, and leaving it blank lets
//     "you may not see this" read as "nobody did it".

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import type { BindingUsability, ProjectDetail } from "../api/dto";

const { calls } = vi.hoisted(() => ({
  calls: {
    updates: [] as unknown[],
    bindings: [] as unknown[],
  },
}));

const state: {
  permissions: string[];
  detail: ProjectDetail | null;
  activity: unknown[];
  actorsHidden: boolean;
} = { permissions: [], detail: null, activity: [], actorsHidden: false };

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: (action: string) => state.permissions.includes(action),
    hasFeature: () => true,
  }),
}));

vi.mock("../stores/projects", () => ({
  useProjectsStore: () => ({
    get current() {
      return state.detail;
    },
    get activity() {
      return state.activity;
    },
    get actorsHidden() {
      return state.actorsHidden;
    },
    activityCursor: null,
    fetchProject: async () => state.detail,
    fetchActivity: async () => undefined,
    update: async (_id: string, input: unknown) => {
      calls.updates.push(input);
    },
    bindWorkspace: async (_id: string, input: unknown) => {
      calls.bindings.push(input);
    },
    unbindWorkspace: async () => undefined,
  }),
}));

vi.mock("../stores/nodes", () => ({
  useNodesStore: () => ({
    fetchList: async () => [
      { id: "n-1", name: "vm", hostname: "vm.invalid", status: "online" },
    ],
    fetchNode: async () => ({
      id: "n-1",
      workspace_roots: [{ path: "/srv", is_enabled: true }],
    }),
  }),
}));

import ProjectDetailView from "./ProjectDetailView.vue";

function binding(usability: BindingUsability, path = "/srv/app") {
  return {
    id: `b-${usability}`,
    node_id: "n-1",
    node_name: "vm",
    node_enabled: true,
    path,
    label: null,
    is_primary: false,
    usability,
    created_at: "2026-08-08T00:00:00Z",
  };
}

function project(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  return {
    id: "p-1",
    name: "Traqora",
    slug: "traqora",
    description: null,
    status: "active",
    owner_user_id: "u-1",
    owner_name: "Alice",
    workspace_count: 1,
    node_count: 1,
    active_session_count: 0,
    last_activity_at: null,
    created_at: "2026-08-08T00:00:00Z",
    updated_at: "2026-08-08T00:00:00Z",
    workspaces: [],
    ...overrides,
  } as ProjectDetail;
}

function testRouter(): Router {
  const blank = { template: "<div/>" };
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/projects", name: "projects", component: blank },
      { path: "/projects/:id", name: "project-detail", component: blank },
      { path: "/sessions", name: "sessions", component: blank },
      { path: "/dashboard", name: "dashboard", component: blank },
      { path: "/nodes", name: "nodes", component: blank },
      { path: "/login", name: "login", component: blank },
    ],
  });
}

async function render() {
  const router = testRouter();
  await router.push("/projects/p-1");
  await router.isReady();
  const wrapper = mount(ProjectDetailView, {
    props: { id: "p-1" },
    global: { plugins: [router] },
  });
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
  await wrapper.vm.$nextTick();
  return wrapper;
}

describe("ProjectDetailView bindings", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    state.permissions = ["project.view"];
    state.activity = [];
    state.actorsHidden = false;
    state.detail = null;
    calls.updates = [];
    calls.bindings = [];
  });

  it("distinguishes all four usability states in words, not only by colour", async () => {
    state.detail = project({
      workspaces: [
        binding("usable", "/srv/ok"),
        binding("node_offline", "/srv/off"),
        binding("node_disabled", "/srv/gone"),
        binding("outside_allowed_root", "/srv/withdrawn"),
      ],
    });
    const wrapper = await render();
    const text = wrapper.text();

    expect(text).toContain("Machine offline");
    expect(text).toContain("Machine removed or disabled");
    // The one most easily confused with "offline", and the one whose fix is
    // different: waiting will not help.
    expect(text).toContain("no longer allows this directory");

    const rows = wrapper.findAll(".bindings li");
    expect(rows).toHaveLength(4);
    // Every reason carries a mark *and* words; colour alone would exclude anyone
    // who cannot distinguish them.
    expect(wrapper.findAll(".mark")).toHaveLength(4);
  });

  it("only offers Open session on a binding that could actually start one", async () => {
    state.detail = project({
      workspaces: [
        binding("usable", "/srv/ok"),
        binding("node_offline", "/srv/off"),
      ],
    });
    const wrapper = await render();
    const buttons = wrapper.findAll(".bindings li button");
    const open = buttons.filter((b) => b.text() === "Open session");
    expect(open).toHaveLength(2);
    expect(open[0].attributes("disabled")).toBeUndefined();
    expect(open[1].attributes("disabled")).toBeDefined();
  });

  it("offers no Open session at all on an archived project", async () => {
    state.detail = project({
      status: "archived",
      workspaces: [binding("usable")],
    });
    const wrapper = await render();
    const open = wrapper
      .findAll("button")
      .filter((b) => b.text() === "Open session");
    expect(open[0].attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("archived");
  });

  it("hides project management controls from someone who cannot manage", async () => {
    state.detail = project({ workspaces: [binding("usable")] });
    const wrapper = await render();
    const labels = wrapper.findAll("button").map((b) => b.text());
    expect(labels).not.toContain("Archive");
    expect(labels).not.toContain("Unbind");
  });

  it("lets an Admin edit the project and choose paused", async () => {
    state.permissions = ["project.view", "project.manage"];
    state.detail = project();
    const wrapper = await render();

    await wrapper
      .findAll("button")
      .find((button) => button.text() === "Edit")!
      .trigger("click");
    const dialog = wrapper.get('[aria-label="Edit project"]');
    await dialog.get("input").setValue("Traqora 2");
    await dialog.get("textarea").setValue("A description");
    await dialog.get("select").setValue("paused");
    await dialog
      .findAll("button")
      .find((button) => button.text() === "Save")!
      .trigger("click");
    await Promise.resolve();

    expect(calls.updates).toContainEqual({
      name: "Traqora 2",
      description: "A description",
      status: "paused",
    });
  });

  it("binds a workspace through the project page", async () => {
    state.permissions = ["project.view", "project.manage"];
    state.detail = project();
    const wrapper = await render();
    const bind = wrapper
      .findAll("button")
      .find((button) => button.text() === "Bind workspace")!;
    await bind.trigger("click");
    await Promise.resolve();

    const dialog = wrapper.get('[aria-label="Bind workspace"]');
    await dialog.get("select").setValue("n-1");
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
    await dialog.find('input[placeholder^="/path"]').setValue("/srv/app");
    await dialog
      .findAll("button")
      .find((button) => button.text() === "Bind")!
      .trigger("click");
    await Promise.resolve();

    expect(calls.bindings).toContainEqual({
      node_id: "n-1",
      path: "/srv/app",
      label: undefined,
      is_primary: true,
    });
  });
});

describe("ProjectDetailView activity", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    state.permissions = ["project.view"];
    state.detail = project();
    state.activity = [
      {
        id: "e-1",
        kind: "workspace.bound",
        occurred_at: "2026-08-08T00:00:00Z",
        payload: { node_name: "vm", path: "/srv/app" },
        actor_id: null,
        actor_name: null,
        session_id: null,
      },
    ];
    state.actorsHidden = false;
  });

  it("says why the actor is missing instead of leaving a bare dash", async () => {
    // Without the sentence, a column of dashes reads as "these events had no
    // actor" — which is a different, and false, statement.
    state.actorsHidden = true;
    const wrapper = await render();
    await wrapper
      .findAll("button")
      .filter((b) => b.text() === "Activity")[0]
      .trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("audit permission");
  });

  it("says nothing about hidden actors when the reader may see them", async () => {
    state.actorsHidden = false;
    const wrapper = await render();
    await wrapper
      .findAll("button")
      .filter((b) => b.text() === "Activity")[0]
      .trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).not.toContain("audit permission");
  });

  it("labels an activity kind rather than printing its raw key", async () => {
    // The defect the browser smoke test caught: the timeline was pointed at the
    // *audit* label map, whose keys are a disjoint set, so every row rendered its
    // wire value. Nothing failed; it just looked unfinished.
    const wrapper = await render();
    expect(wrapper.text()).toContain("綁定 Workspace");
    expect(wrapper.text()).not.toContain("workspace.bound");
  });
});
