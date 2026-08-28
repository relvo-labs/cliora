import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { ProjectRepository } from "../../api/dto";
import * as auth from "../../stores/auth";
import ProjectRepositories from "./ProjectRepositories.vue";

// `HD-15`. **Three states and the differences between them are the whole point.**
//
// A repository that stopped being read looks exactly like one where nothing has been
// merged, and that is the failure `provider_sync_error` was made a stored column for
// (ADR 0043 §5). If this panel renders the three identically, the column is a database
// row nobody can act on.

function repo(over: Partial<ProjectRepository> = {}): ProjectRepository {
  return {
    id: "r1",
    project_id: "p1",
    scheme: "https",
    host: "github.com",
    path: "cliora/demo",
    default_branch: "main",
    label: null,
    url: "https://github.com/cliora/demo",
    created_at: new Date().toISOString(),
    provider_synced_at: null,
    next_provider_sync_at: null,
    provider_sync_error: null,
    provider_sync_stopped: false,
    ...over,
  };
}

async function render(repositories: ProjectRepository[]) {
  vi.spyOn(auth, "api").mockReturnValue({
    listProjectRepositories: vi.fn().mockResolvedValue(repositories),
  } as never);
  const wrapper = mount(ProjectRepositories, {
    props: { projectId: "p1", canManage: true },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  await wrapper.vm.$nextTick();
  return wrapper;
}

describe("ProjectRepositories — provider sync state", () => {
  it("says a repository has never been synced rather than showing nothing", async () => {
    const wrapper = await render([repo()]);
    expect(wrapper.text()).toContain("尚未同步過");
  });

  it("shows when the last sync was and when the next one is due", async () => {
    const wrapper = await render([
      repo({
        provider_synced_at: new Date(Date.now() - 120_000).toISOString(),
        next_provider_sync_at: new Date(Date.now() + 180_000).toISOString(),
      }),
    ]);
    const text = wrapper.text();
    expect(text).toContain("上次同步");
    expect(text).toContain("下次");
  });

  it("shows a failing sync without claiming it has stopped", async () => {
    // One failure is not three. Reporting it as "stopped" would tell somebody to go and
    // fix a credential that is about to work on the next pass.
    const wrapper = await render([
      repo({
        provider_sync_error: "403: rate limited",
        provider_sync_stopped: false,
      }),
    ]);
    const text = wrapper.text();
    expect(text).toContain("最近一次同步失敗");
    expect(text).toContain("403: rate limited");
    expect(text).not.toContain("已停止同步");
  });

  it("says a stopped repository has stopped, and why, and what fixes it", async () => {
    // **The assertion this whole component exists for.** All three parts are needed: a
    // reader who only learns "stopped" goes looking for the reason, and one who only
    // learns the reason does not know that nothing will retry until they act.
    const wrapper = await render([
      repo({
        provider_sync_error: "401: Bad credentials",
        provider_sync_stopped: true,
      }),
    ]);
    const text = wrapper.text();
    expect(text).toContain("已停止同步");
    expect(text).toContain("401: Bad credentials");
    expect(text).toContain("下一輪");
  });

  it("distinguishes the three states rather than rendering one shape", async () => {
    // The regression this guards is a refactor that collapses the branches into one
    // "sync status" line: every individual assertion above would still pass on a
    // component that printed the same sentence three times.
    const quiet = await render([
      repo({ provider_synced_at: new Date().toISOString() }),
    ]);
    const failing = await render([repo({ provider_sync_error: "403" })]);
    const stopped = await render([
      repo({ provider_sync_error: "401", provider_sync_stopped: true }),
    ]);
    const texts = [quiet, failing, stopped].map((wrapper) =>
      wrapper.get("[data-repo-sync]").text(),
    );
    expect(new Set(texts).size).toBe(3);
  });
});
