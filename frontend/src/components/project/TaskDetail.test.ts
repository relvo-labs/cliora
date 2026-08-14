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

  it("shows the two V2.4 modes rather than hiding them", async () => {
    // Removing them would turn "will this platform ever open a PR" into a question
    // somebody has to ask a person. They are refused at dispatch, naming the version.
    const wrapper = render({ canEdit: true });
    const values = wrapper.findAll("option").map((o) => o.attributes("value"));
    expect(values).toContain("pull_request");
    expect(values).toContain("existing_pr");
  });

  it("warns on the default, because the default cannot be dispatched", async () => {
    const wrapper = render({
      canEdit: true,
      task: { delivery: "pull_request" },
    });
    expect(wrapper.text()).toContain("從 V2.4 起生效");
    expect(wrapper.text()).toContain("artifact");
  });

  it("shows a badge instead of a select without task.update", async () => {
    const wrapper = render({ canEdit: false });
    expect(wrapper.findAll("select")).toHaveLength(0);
  });
});
