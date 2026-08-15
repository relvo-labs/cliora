import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { ProcessDefinition, Task } from "../../api/dto";
import SourceBadge from "../ui/SourceBadge.vue";
import { SOURCE_AGENT, SOURCE_MACHINE, SOURCE_PLATFORM } from "../ui/labels";
import TaskDetail from "./TaskDetail.vue";

const process: ProcessDefinition = {
  key: "default",
  version: "1",
  source: "platform",
  lanes: [],
  readiness: [],
  gates: [],
  templates: {},
};

function task(): Task {
  return {
    id: "task-1",
    project_id: "project-1",
    card_ref: "TASK-1",
    title: "證明失敗項目",
    description: null,
    objective: "看清楚失敗原因",
    scope: null,
    non_goals: null,
    stage: "verify",
    card_kind: "implementation",
    risk: "high",
    priority: "normal",
    owner_user_id: null,
    epic_id: null,
    user_story_id: null,
    readiness: {},
    gates: {},
    acceptance_criteria: [
      {
        text: "型別檢查",
        result: "failed",
        source: SOURCE_MACHINE,
        command: "npm run typecheck",
      },
      {
        text: "Agent 摘要",
        result: "passed",
        source: SOURCE_AGENT,
        summary: "完成",
      },
    ],
    links: {
      evidence: [
        {
          source: SOURCE_PLATFORM,
          label: "Run 狀態",
          value: "failed",
        },
      ],
    },
    required_labels: [],
    version: 1,
    source: SOURCE_PLATFORM,
    repository_id: null,
    base_branch: null,
    delivery: "artifact",
    target_branch: null,
    existing_pr_ref: null,
    verification_commands: [],
    force_done_reason: null,
    force_done_by: null,
    force_done_at: null,
    required_secrets: [],
    assigned_runner_id: null,
    requirement_id: null,
    proposal_id: null,
    depends_on: [],
    blocking_refs: [],
    created_at: "2026-08-12T00:00:00Z",
    updated_at: "2026-08-12T00:00:00Z",
  };
}

// One mount helper for the V2.3 tests below. The original test mounts inline and is
// left as it is: it pins a different property and rewriting it would put an unrelated
// diff in front of whoever reviews this.
function render(
  overrides: {
    canEdit?: boolean;
    client?: Record<string, unknown>;
    task?: Partial<ReturnType<typeof task>>;
  } = {},
) {
  return mount(TaskDetail, {
    props: {
      task: { ...task(), ...(overrides.task ?? {}) },
      process,
      client: {
        decideGate: vi.fn(),
        updateTask: vi.fn(),
        ...(overrides.client ?? {}),
      } as never,
      canApprove: false,
      canEdit: overrides.canEdit ?? false,
      canStartSession: false,
    },
    global: { stubs: { RouterLink: true } },
  });
}

describe("TaskDetail", () => {
  it("keeps a failed check expanded and preserves evidence provenance", () => {
    const wrapper = mount(TaskDetail, {
      props: {
        task: task(),
        process,
        client: { decideGate: vi.fn() } as never,
        canApprove: false,
        canEdit: false,
        canStartSession: false,
      },
      global: { stubs: { RouterLink: true } },
    });

    const failed = wrapper.get("[data-failed-check]");
    expect(failed.find("details").exists()).toBe(false);
    expect(failed.text()).toContain("npm run typecheck");
    expect(wrapper.findAll(".criteria details")).toHaveLength(1);
    expect(wrapper.get("[data-evidence]").text()).toContain("Run 狀態");
    expect(wrapper.findAllComponents(SourceBadge)).toHaveLength(4);
  });
});

describe("TaskDetail execution settings", () => {
  // **The gap this closes made the whole V2.3 dispatch path unreachable.** A new card
  // defaults to `delivery: pull_request`, which is refused at dispatch until V2.4 — and
  // until now nothing on this page could change it. A field the platform acts on and
  // the console cannot set is worse than one the platform ignores.
  it("lets an editor change source and delivery", async () => {
    const updateTask = vi.fn().mockResolvedValue({});
    const wrapper = render({ canEdit: true, client: { updateTask } });
    const selects = wrapper.findAll("select");
    expect(selects.length).toBeGreaterThanOrEqual(2);

    const delivery = selects.find((s) =>
      s.findAll("option").some((o) => o.attributes("value") === "branch"),
    );
    expect(delivery).toBeDefined();
    await delivery!.setValue("artifact");
    // The optimistic lock travels with the change: two tabs editing one card is the
    // case `version` exists for.
    expect(updateTask).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        delivery: "artifact",
        version: expect.any(Number),
      }),
    );
  });

  it("offers all five delivery modes", async () => {
    const wrapper = render({ canEdit: true });
    const values = wrapper.findAll("option").map((o) => o.attributes("value"));
    for (const mode of [
      "none",
      "artifact",
      "branch",
      "pull_request",
      "existing_pr",
    ]) {
      expect(values).toContain(mode);
    }
  });

  // The panel says what a mode still needs, **on the panel**, because the fix for
  // every one of these is a field on this same panel. Meeting it as a 409 after
  // pressing dispatch is how somebody concludes the mode does not work.
  it("asks for a target branch on the panel rather than at the 409", async () => {
    const wrapper = render({
      canEdit: true,
      task: { delivery: "pull_request", source: "repo", target_branch: null },
    });
    expect(wrapper.text()).toContain("target branch");
    // And the field exists to answer it.
    const placeholders = wrapper
      .findAll("input")
      .map((i) => i.attributes("placeholder"));
    expect(placeholders).toContain("main");
  });

  it("names the one combination the two independent fields cannot form", async () => {
    const wrapper = render({
      canEdit: true,
      task: { delivery: "pull_request", source: "none" },
    });
    // A pull request needs code. Said before dispatch, not after.
    expect(wrapper.text()).toContain("要交付程式碼變更");
  });

  it("explains the cliora/ namespace where the branch is typed", async () => {
    const wrapper = render({
      canEdit: true,
      task: {
        delivery: "existing_pr",
        source: "existing_branch",
        base_branch: "feature/login",
      },
    });
    // This boundary reads as a bug to whoever hits it, so it is explained at the
    // point of editing rather than only in the dispatch refusal.
    expect(wrapper.text()).toContain("cliora/");
    expect(wrapper.text()).toContain("只能接續平台自己開的 PR");
  });

  it("lets a person edit every execution field the API accepts", async () => {
    // The defect this pins is the one V2.3 shipped and V2.4 repeated: the backend
    // accepts the field, the console can only display it, and the mode is unreachable
    // from the console. A count is the wrong assertion — the placeholders name which.
    const wrapper = render({
      canEdit: true,
      task: { delivery: "pull_request", source: "existing_branch" },
    });
    const placeholders = wrapper
      .findAll("input")
      .map((i) => i.attributes("placeholder"));
    expect(placeholders).toContain("main"); // target branch
    expect(placeholders).toContain("cliora/TASK-1-1"); // base branch
    expect(placeholders).toContain("docker node20"); // tags
    expect(placeholders).toContain("NPM_TOKEN"); // secrets
  });

  it("shows a badge instead of a select without task.update", async () => {
    const wrapper = render({ canEdit: false });
    expect(wrapper.findAll("select")).toHaveLength(0);
  });
});
