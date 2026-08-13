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

describe("TaskDetail", () => {
  it("keeps a failed check expanded and preserves evidence provenance", () => {
    const wrapper = mount(TaskDetail, {
      props: {
        task: task(),
        process,
        client: { decideGate: vi.fn() } as never,
        canApprove: false,
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
