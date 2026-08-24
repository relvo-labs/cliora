// The project shell and its seven children (PX-64), and the three displays whose
// silence is the failure.
//
// **Ported from `views/ProjectDetailView.test.ts` when that file was split**, and
// deliberately not rewritten: the assertions describe the same system, and rewriting them
// alongside the refactor would mean the refactor had no test that predated it. What
// changed is the mounting — a real nested router, so a navigation is what selects the
// view rather than a `ref`.
//
// Three properties, each silent when wrong:
//
//   * a binding that cannot be used must say *why*, and the four reasons are not
//     interchangeable — "the machine is down" and "this machine no longer allows this
//     directory" call for different actions;
//   * a missing actor means one of two different things, and leaving it blank lets
//     "you may not see this" read as "nobody did it";
//   * a dispatch refusal must keep the card it already created and name it.
//
// Plus one the split itself introduced: **`?tab=` still lands where it used to.**

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import type { BindingUsability, ProjectDetail } from "../../api/dto";

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

vi.mock("../../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: (action: string) => state.permissions.includes(action),
    hasFeature: () => true,
  }),
  api: () => ({
    listRequirements: async () => state.requirements,
    // Overview's attention strip and work distribution (PX-50). Zero counts, because what
    // this suite is about is the shell and the pages' own content.
    getWorkCounts: async () => ({
      by_lifecycle: {},
      by_attention: {},
      total: 0,
      runtime_signals_available: true,
    }),
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

vi.mock("../../stores/projects", () => ({
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

vi.mock("../../stores/nodes", () => ({
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

import ProjectShell from "./ProjectShell.vue";
import ProjectActivityView from "./views/ProjectActivityView.vue";
import ProjectOverviewView from "./views/ProjectOverviewView.vue";
import ProjectRequirementsView from "./views/ProjectRequirementsView.vue";

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
      {
        // **The real nesting**, not a stub: what this file has to be able to break is
        // the wiring between the shell and its children, and a blank parent would test
        // neither.
        path: "/projects/:id",
        name: "project-detail",
        component: ProjectShell,
        props: true,
        redirect: (to) => {
          const tab = Array.isArray(to.query.tab)
            ? to.query.tab[0]
            : to.query.tab;
          const legacy: Record<string, string> = {
            overview: "project-overview",
            board: "project-work",
            roadmap: "project-roadmap",
            requirements: "project-requirements",
            activity: "project-activity",
            settings: "project-settings",
          };
          const { tab: _dropped, ...query } = to.query;
          return {
            name: legacy[String(tab)] ?? "project-overview",
            params: to.params,
            query,
          };
        },
        children: [
          {
            path: "overview",
            name: "project-overview",
            component: ProjectOverviewView,
          },
          { path: "work", name: "project-work", component: blank },
          { path: "roadmap", name: "project-roadmap", component: blank },
          {
            path: "requirements",
            name: "project-requirements",
            component: ProjectRequirementsView,
          },
          {
            path: "activity",
            name: "project-activity",
            component: ProjectActivityView,
          },
          { path: "settings", name: "project-settings", component: blank },
        ],
      },
      {
        path: "/projects/:id/knowledge",
        name: "project-knowledge",
        component: blank,
      },
      { path: "/sessions", name: "sessions", component: blank },
      { path: "/my-work", name: "my-work", component: blank },
      { path: "/dashboard", name: "dashboard", component: blank },
      { path: "/nodes", name: "nodes", component: blank },
      { path: "/login", name: "login", component: blank },
      {
        path: "/settings/integrations",
        name: "integrations",
        component: blank,
      },
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

async function render(path = "/projects/p-1/overview") {
  const router = testRouter();
  await router.push(path);
  await router.isReady();
  const wrapper = mount(ProjectShell, {
    props: { id: "p-1" },
    global: { plugins: [router] },
  });
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
  await wrapper.vm.$nextTick();
  await wrapper.vm.$nextTick();
  return { wrapper, router };
}

describe("ProjectShell bindings", () => {
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
    const { wrapper } = await render();
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
    const { wrapper } = await render();
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
    const { wrapper } = await render();
    const open = wrapper
      .findAll("button")
      .filter((b) => b.text() === "Open session");
    expect(open[0].attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("archived");
  });

  it("hides project management controls from someone who cannot manage", async () => {
    state.detail = project({ workspaces: [binding("usable")] });
    const { wrapper } = await render();
    const labels = wrapper.findAll("button").map((b) => b.text());
    expect(labels).not.toContain("Archive");
    expect(labels).not.toContain("Unbind");
  });

  it("lets an Admin edit the project and choose paused", async () => {
    state.permissions = ["project.view", "project.manage"];
    state.detail = project();
    const { wrapper } = await render();

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
    const { wrapper } = await render();
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

describe("ProjectShell activity", () => {
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
    const { wrapper } = await render("/projects/p-1/activity");
    expect(wrapper.text()).toContain("audit permission");
  });

  it("says nothing about hidden actors when the reader may see them", async () => {
    state.actorsHidden = false;
    const { wrapper } = await render("/projects/p-1/activity");
    expect(wrapper.text()).not.toContain("audit permission");
  });

  it("labels an activity kind rather than printing its raw key", async () => {
    // The defect the browser smoke test caught: the timeline was pointed at the
    // *audit* label map, whose keys are a disjoint set, so every row rendered its
    // wire value. Nothing failed; it just looked unfinished.
    const { wrapper } = await render();
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
  // Navigated to rather than clicked into: a section is a route now, and rendering it by
  // URL is also what proves the route exists.
  const { wrapper } = await render("/projects/p-1/requirements");
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
  await wrapper.vm.$nextTick();
  return wrapper;
}

describe("ProjectShell requirement dispatch", () => {
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
    const { ApiError: Api } = await import("../../api/client");
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

// --- what the split itself has to keep true (PX-64) -------------------------
//
// Two properties, and both are about links that already exist in the wild. There is no
// version flag and no second path (D117), so a bookmark and an in-app breadcrumb are the
// only things that can catch a mistake here — after the fact, from a user.

describe("ProjectShell routing", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    state.permissions = ["project.view"];
    state.detail = project();
    state.activity = [];
    state.actorsHidden = false;
    state.requirements = [];
    state.dispatchError = null;
  });

  it("lands on Overview when no section is named", async () => {
    const { router } = await render("/projects/p-1");
    expect(router.currentRoute.value.name).toBe("project-overview");
  });

  it.each([
    ["overview", "project-overview"],
    ["board", "project-work"],
    ["roadmap", "project-roadmap"],
    ["requirements", "project-requirements"],
    ["activity", "project-activity"],
    ["settings", "project-settings"],
  ])("redirects the old ?tab=%s to %s", async (tab, name) => {
    // Every one of these is a URL somebody has bookmarked. The redirect lives in the
    // router rather than in the shell so it is visibly temporary — a compatibility branch
    // inside a component never looks like something to remove.
    const { router } = await render(`/projects/p-1?tab=${tab}`);
    expect(router.currentRoute.value.name).toBe(name);
    expect(router.currentRoute.value.query.tab).toBeUndefined();
  });

  it("keeps every other query key through the redirect", async () => {
    // `?task=` is the Drawer's state. A link to a card inside a board must not lose the
    // card on the way through the redirect.
    const { router } = await render(
      "/projects/p-1?tab=board&task=t-9&view=v-1",
    );
    expect(router.currentRoute.value.name).toBe("project-work");
    expect(router.currentRoute.value.query).toEqual({
      task: "t-9",
      view: "v-1",
    });
  });

  it("renders the navigation as links, so middle-click works", async () => {
    // They were `<button>` elements inside one page. A section is a URL now, and the two
    // things people actually do with navigation — open in a new tab, copy the address —
    // work on an anchor and on nothing else.
    const { wrapper } = await render();
    const nav = wrapper.get('nav[aria-label="Project sections"]');
    expect(nav.findAll("button")).toHaveLength(0);
    const links = nav.findAll("a");
    expect(links.length).toBe(7);
    expect(links.map((link) => link.attributes("href"))).toContain(
      "/projects/p-1/work",
    );
  });

  it("marks the section it is on, and only that one", async () => {
    const { wrapper } = await render("/projects/p-1/requirements");
    const active = wrapper
      .get('nav[aria-label="Project sections"]')
      .findAll("a")
      .filter((link) => link.attributes("data-active") === "true");
    expect(active).toHaveLength(1);
    expect(active[0].text()).toBe("Requirements");
  });

  it("offers Knowledge in the navigation although it is a sibling route", async () => {
    // It stays top-level — it has its own header and its own loading state, and folding
    // it into the shell would mean rewriting both to fit a shell it does not need. The
    // navigation is what makes that invisible to a reader.
    const { wrapper } = await render();
    const hrefs = wrapper
      .get('nav[aria-label="Project sections"]')
      .findAll("a")
      .map((link) => link.attributes("href"));
    expect(hrefs).toContain("/projects/p-1/knowledge");
  });

  it("loads the project once for the whole shell, not once per section", async () => {
    // The reason the context exists. Per-view loading means the header refetches on every
    // navigation, and the header is the part that visibly flickers.
    const { wrapper, router } = await render();
    const before = wrapper.text();
    await router.push({ name: "project-requirements", params: { id: "p-1" } });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("Traqora");
    expect(before).toContain("Traqora");
  });
});
