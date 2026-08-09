import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory } from "vue-router";

import { ApiError } from "../api/client";
import ProjectsView from "./ProjectsView.vue";

const { state, calls } = vi.hoisted(() => ({
  state: {
    list: [] as unknown[],
    listError: null as unknown,
    canManage: true,
  },
  calls: { creates: [] as unknown[] },
}));

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: () => state.canManage,
  }),
}));

vi.mock("../stores/projects", () => ({
  useProjectsStore: () => ({
    get list() {
      return state.list;
    },
    fetchList: async () => {
      if (state.listError) throw state.listError;
      return state.list;
    },
    create: async (input: unknown) => {
      calls.creates.push(input);
      return { id: "p-1" };
    },
  }),
}));

async function render() {
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: "/projects", name: "projects", component: ProjectsView },
      {
        path: "/projects/:id",
        name: "project-detail",
        component: { template: "<div />" },
      },
    ],
  });
  await router.push("/projects");
  await router.isReady();
  const wrapper = mount(ProjectsView, {
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<main><slot /></main>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

describe("ProjectsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    state.list = [];
    state.listError = null;
    state.canManage = true;
    calls.creates = [];
  });

  it("creates a project with its optional identifier and description", async () => {
    const wrapper = await render();
    await wrapper.get("button.primary").trigger("click");
    const dialog = wrapper.get('[aria-label="New project"]');
    const inputs = dialog.findAll("input");
    await inputs[0].setValue("Traqora");
    await inputs[1].setValue("traqora-platform");
    await dialog.get("textarea").setValue("Cross-node work");
    await dialog
      .findAll("button")
      .find((button) => button.text() === "Create")!
      .trigger("click");
    await flushPromises();

    expect(calls.creates).toEqual([
      {
        name: "Traqora",
        slug: "traqora-platform",
        description: "Cross-node work",
      },
    ]);
  });

  it("renders a feature-off 404 as an intentional empty state", async () => {
    state.listError = new ApiError("NOT_FOUND", "Not found", 404, "req-off");
    const wrapper = await render();
    expect(wrapper.text()).toContain("Projects are not enabled");
    expect(wrapper.text()).not.toContain("Could not load projects");
  });

  it("shows the request id and retry for an operational failure", async () => {
    state.listError = new ApiError("INTERNAL", "safe", 500, "req-500");
    const wrapper = await render();
    expect(wrapper.text()).toContain("Request ID: req-500");
    expect(wrapper.text()).toContain("Retry");
  });
});
