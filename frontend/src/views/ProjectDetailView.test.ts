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
    cards: [] as Record<string, unknown>[],
    dispatches: [] as string[],
  },
}));

const state: {
  permissions: string[];
  detail: ProjectDetail | null;
  activity: unknown[];
  actorsHidden: boolean;
  requirements: unknown[];
  dispatchError: unknown;
} = {
  permissions: [],
  detail: null,
  activity: [],
  actorsHidden: false,
  requirements: [],
  dispatchError: null,
};

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: (action: string) => state.permissions.includes(action),
    hasFeature: () => true,
  }),
  api: () => ({
    listRequirements: async () => state.requirements,
    createRequirement: async () => ({ id: "r-1" }),
    listPatchProposals: async () => [],
    decidePatchProposal: async () => undefined,
    createTask: async (_project: string, input: Record<string, unknown>) => {
      calls.cards.push(input);
      return { task: { id: "t-1", card_ref: "TASK-9" }, warnings: [] };
    },
    dispatchTask: async (taskId: string) => {
      calls.dispatches.push(taskId);
      if (state.dispatchError) throw state.dispatchError;
      return { run_id: "run-1", status: "queued" };
    },
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
      {
        path: "/projects/:id/requirements/:requirementId",
        name: "requirement-detail",
        component: blank,
      },
      {
        path: "/projects/:id/tasks/:taskId",
        name: "task-detail",
        component: blank,
      },
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
    state.requirements = [];
    state.dispatchError = null;
    calls.updates = [];
    calls.bindings = [];
    calls.cards = [];
    calls.dispatches = [];
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

// --- V2.5: sending a requirement to an agent (RQ-10 §1.2, FR-SPEC-002) ------
//
// Two requests behind one button, and **the second one fails often** — every dispatch
// refusal this phase added lands there. So most of what these defend is the failure
// path, which is where a convenience button becomes a trap.

function requirement(status: string, ref = "REQ-1") {
  return {
    id: "r-1",
    project_id: "p-1",
    card_ref: ref,
    raw_text: "報表匯出很慢",
    status,
    created_by: null,
    approved_by: null,
    approved_at: null,
    spec_count: 0,
    created_at: "2026-08-14T00:00:00Z",
    updated_at: "2026-08-14T00:00:00Z",
  };
}

async function requirementsTab(status: string) {
  state.detail = project();
  state.requirements = [requirement(status)];
  const wrapper = await render();
  await wrapper.get("[data-tab='requirements']").trigger("click");
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
  await wrapper.vm.$nextTick();
  return wrapper;
}

describe("ProjectDetailView requirement dispatch", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    state.permissions = ["project.view", "task.create", "run.dispatch"];
    state.activity = [];
    state.actorsHidden = false;
    state.detail = null;
    state.requirements = [];
    state.dispatchError = null;
    calls.cards = [];
    calls.dispatches = [];
  });

  it("creates a clarification card with the settings the server will accept", async () => {
    // `delivery: artifact` and no secrets, because dispatch refuses anything else for
    // this kind — a button that builds a card the server then rejects is worse than no
    // button.
    const wrapper = await requirementsTab("intake");
    await wrapper.get("[data-clarify='REQ-1']").trigger("click");
    for (let i = 0; i < 6; i += 1) await Promise.resolve();

    expect(calls.cards).toHaveLength(1);
    expect(calls.cards[0]).toMatchObject({
      card_kind: "clarification",
      requirement_id: "r-1",
      delivery: "artifact",
      stage: "ready",
    });
    expect(calls.cards[0].required_secrets).toBeUndefined();
    expect(calls.dispatches).toEqual(["t-1"]);
  });

  it("will not offer decomposition until the specification is approved", async () => {
    // The same sentence the API answers with. A control that is greyed out with no
    // reason is one people look for a way round.
    const wrapper = await requirementsTab("intake");
    const decompose = wrapper.get("[data-decompose='REQ-1']");
    expect(decompose.attributes("disabled")).toBeDefined();
    expect(decompose.attributes("title")).toContain("先核准規格");
  });

  it("offers decomposition and not clarification once approved", async () => {
    const wrapper = await requirementsTab("approved");
    expect(
      wrapper.get("[data-decompose='REQ-1']").attributes("disabled"),
    ).toBeUndefined();
    expect(
      wrapper.get("[data-clarify='REQ-1']").attributes("disabled"),
    ).toBeDefined();
  });

  it("keeps the card when dispatch is refused, and says which card it kept", async () => {
    // The most important one. Dispatch fails for reasons that are *waits* — no runner is
    // online yet — as well as for mistakes, and a button that deleted the card on failure
    // would destroy a perfectly good card while somebody starts a machine.
    const { ApiError: Api } = await import("../api/client");
    state.dispatchError = new Api(
      "PROJECT_NO_REPOSITORY",
      "這個專案還沒有登記儲存庫",
      409,
    );
    const wrapper = await requirementsTab("intake");
    await wrapper.get("[data-clarify='REQ-1']").trigger("click");
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await wrapper.vm.$nextTick();

    expect(calls.cards).toHaveLength(1);
    const text = wrapper.text();
    expect(text).toContain("TASK-9");
    expect(text).toContain("已建立");
    expect(text).toContain("這個專案還沒有登記儲存庫");
    // And the card is reachable, so a second click does not make a second card.
    expect(wrapper.find("[data-dispatched='REQ-1']").exists()).toBe(true);
  });

  it("hides both buttons from somebody who may create but not dispatch", async () => {
    // Queueing work spends compute; `run.dispatch` is deliberately not covered by
    // `task.create` (ADR 0029), and the console must not imply otherwise.
    state.permissions = ["project.view", "task.create"];
    const wrapper = await requirementsTab("intake");
    expect(wrapper.find("[data-clarify='REQ-1']").exists()).toBe(false);
    expect(wrapper.find("[data-decompose='REQ-1']").exists()).toBe(false);
  });
});
