import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProjectSecret } from "../../api/dto";
import ProjectSecrets from "./ProjectSecrets.vue";

const state: { list: ProjectSecret[] } = { list: [] };

vi.mock("../../stores/auth", () => ({
  api: () => ({
    listSecrets: async () => state.list,
    createSecret: async () => state.list[0],
    rotateSecret: async () => state.list[0],
    deleteSecret: async () => undefined,
  }),
}));

function secret(overrides: Partial<ProjectSecret> = {}): ProjectSecret {
  return {
    id: "s-1",
    project_id: "p-1",
    name: "GITHUB_TOKEN",
    kind: "env",
    created_by: "u-1",
    created_at: "2026-08-13T09:00:00Z",
    rotated_at: null,
    last_used_at: null,
    ...overrides,
  };
}

async function render(gitDeliveryEnabled = false) {
  const wrapper = mount(ProjectSecrets, {
    props: { projectId: "p-1", gitDeliveryEnabled },
    global: {
      stubs: {
        EmptyState: true,
        UiButton: { template: "<button><slot/></button>" },
      },
    },
  });
  await flushPromises();
  return wrapper;
}

describe("ProjectSecrets", () => {
  beforeEach(() => {
    state.list = [secret()];
  });

  it("has no way to render a value, and no prop that could carry one", async () => {
    // Asserted against the **type surface** rather than against the rendered output: a
    // page that happens not to print a value today would still pass if a `value` field
    // appeared on the DTO tomorrow. `ProjectSecret` has no such field, and this test
    // fails to compile if one is added.
    const row: ProjectSecret = secret();
    expect(Object.keys(row)).not.toContain("value");
    const wrapper = await render();
    expect(wrapper.text()).toContain("GITHUB_TOKEN");
    // And there is no affordance implying a readable copy exists somewhere.
    expect(wrapper.text()).not.toContain("顯示");
    expect(wrapper.text()).not.toContain("複製");
  });

  it("puts the master-key consequence on the page rather than in a runbook", async () => {
    // A database backup cannot restore a secret without the key, and the moment
    // somebody needs to know that is before they type one in.
    const wrapper = await render();
    expect(wrapper.text()).toContain("不可復原");
    expect(wrapper.text()).toContain("分開保管");
  });

  it("says what deleting does not do", async () => {
    // Cliora does not know what that token is called at its provider, so "deleted"
    // must not read as "revoked".
    const wrapper = await render();
    await wrapper.findAll("button").at(-1)?.trigger("click");
    const text = wrapper.text();
    expect(text).toContain("不再下放");
    expect(text).toContain("來源系統");
    expect(text).toContain("進行中的執行不受影響");
  });

  it("disables the git kinds with a reason rather than hiding them", async () => {
    // ⊘ rather than absent: hiding them turns "can this platform manage git
    // credentials" into a question somebody has to ask a person (2026-08-13 ruling).
    const wrapper = await render(false);
    await wrapper.find("button").trigger("click");
    const options = wrapper.findAll("option");
    const git = options.filter((o) =>
      o.attributes("value")?.startsWith("git_"),
    );
    expect(git).toHaveLength(2);
    for (const option of git) {
      expect(option.attributes("disabled")).toBeDefined();
      expect(option.text()).toContain("未啟用");
    }
    expect(
      options
        .find((o) => o.attributes("value") === "env")
        ?.attributes("disabled"),
    ).toBeUndefined();
  });

  it("enables the git kinds where the deployment delivers them", async () => {
    const wrapper = await render(true);
    await wrapper.find("button").trigger("click");
    const git = wrapper
      .findAll("option")
      .filter((o) => o.attributes("value")?.startsWith("git_"));
    for (const option of git) {
      expect(option.attributes("disabled")).toBeUndefined();
    }
  });

  it("separates a live credential from one nothing has touched", async () => {
    state.list = [
      secret({ id: "s-1", name: "USED", last_used_at: "2026-08-13T10:00:00Z" }),
      secret({ id: "s-2", name: "UNUSED", last_used_at: null }),
    ];
    const wrapper = await render();
    expect(wrapper.text()).toContain("從未使用");
  });

  it("warns against using the env kind for a git credential", async () => {
    // The UI half of the kind split: an `env` secret reaches the agent's environment,
    // and a git credential there is one the five push constraints cannot reach.
    const wrapper = await render();
    await wrapper.find("button").trigger("click");
    expect(wrapper.text()).toContain("git 憑證請不要用這個類型");
  });
});
