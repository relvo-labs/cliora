// The screen assertions for V2.4's credibility grading (exit conditions 19b, ADR 0033 §3b).
//
// These exist because the backend can get all three levels right and a screen that
// paints them identically makes every one of those decisions worthless. `plan/20` set
// the precedent with "no padlock near a tag"; this is the same kind of test.

import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { EvidenceItem, Task, VerificationReport } from "../../api/dto";
import SourceBadge from "../ui/SourceBadge.vue";

const task = (overrides: Partial<Task> = {}): Task =>
  ({
    id: "t1",
    project_id: "p1",
    card_ref: "TASK-1",
    title: "a card",
    stage: "verify",
    acceptance_criteria: [],
    verification_commands: [],
    force_done_reason: null,
    force_done_by: null,
    force_done_at: null,
    delivery: "none",
    ...overrides,
  }) as unknown as Task;

const report = (
  overrides: Partial<VerificationReport> = {},
): VerificationReport =>
  ({
    id: "r1",
    result: "passed",
    checks: [],
    acceptance_criteria: [],
    remaining_risks: [],
    completion_summary: "did the thing",
    source: "machine_verified",
    run_id: null,
    reported_by_kind: "agent",
    reported_at: "2026-08-14T00:00:00Z",
    ...overrides,
  }) as VerificationReport;

function stubApi(options: {
  reports?: VerificationReport[];
  evidence?: EvidenceItem[];
}) {
  vi.doMock("../../stores/auth", () => ({
    api: () => ({
      listTaskPlans: async () => [],
      listTaskVerification: async () => options.reports ?? [],
      listTaskEvidence: async () => options.evidence ?? [],
    }),
  }));
}

async function render(
  taskValue: Task,
  options: Parameters<typeof stubApi>[0] = {},
) {
  vi.resetModules();
  stubApi(options);
  const Component = (await import("./TaskCompletion.vue")).default;
  const wrapper = mount(Component, { props: { task: taskValue } });
  await new Promise((resolve) => setTimeout(resolve, 0));
  await wrapper.vm.$nextTick();
  return wrapper;
}

describe("the credibility grading is visible, not merely stored", () => {
  it("names an agent's self-report in words rather than in a tooltip", () => {
    const wrapper = mount(SourceBadge, { props: { source: "agent_reported" } });
    // Text, not a title attribute: a qualifier you have to hover for is one nobody
    // reads, and this is the only place a person meets the grading at all.
    expect(wrapper.text()).toContain("未經平台驗證");
    expect(wrapper.html()).not.toContain('title="未經平台驗證"');
  });

  it("renders both origins in the same style, and names the origin in words", () => {
    const fromProject = mount(SourceBadge, {
      props: { source: "machine_verified", origin: "project" },
    });
    const fromCard = mount(SourceBadge, {
      props: { source: "machine_verified", origin: "card" },
    });

    // Equal credibility, equal styling: declaring a check on a card takes
    // `task.approve`, which a run token never holds, so neither was chosen by the
    // agent being verified. A paler card badge would assert something untrue.
    const solidOf = (html: string) =>
      html.match(/class="[^"]*v-solid[^"]*"/g) ?? [];
    expect(solidOf(fromProject.html())).toEqual(solidOf(fromCard.html()));

    expect(fromProject.text()).toContain("專案設定");
    expect(fromCard.text()).toContain("卡片宣告");
  });

  it("does not show an origin for a level where it would be meaningless", () => {
    const wrapper = mount(SourceBadge, {
      props: { source: "agent_reported", origin: "card" },
    });
    // An agent's self-report has no origin: nothing "ran" it.
    expect(wrapper.text()).not.toContain("卡片宣告");
  });
});

describe("the completion panel", () => {
  it("shows the gate before anyone is refused, not only afterwards", async () => {
    const wrapper = await render(
      task({ acceptance_criteria: [{ text: "reject traversal" }] }),
    );

    const gate = wrapper.get('[data-testid="done-gate"]');
    expect(gate.text()).toContain("完成摘要");
    expect(gate.text()).toContain("驗證報告");
    // And it names what is missing, rather than counting it.
    expect(gate.text()).toContain("reject traversal");
  });

  it("puts failed checks first and does not fold them away", async () => {
    const wrapper = await render(task(), {
      reports: [
        report({
          result: "failed",
          checks: [
            { name: "passes", origin: "project", exit_code: 0 },
            { name: "fails", origin: "card", exit_code: 3 },
          ],
        }),
      ],
    });

    const rows = wrapper
      .get('[data-testid="verification"]')
      .findAll("tbody tr");
    expect(rows[0].text()).toContain("fails");
    // Not inside a <details>: the interesting half of a report is the half that failed.
    expect(wrapper.html()).not.toContain("<details");
  });

  it("shows an agent-reported exit code without the machine-fact style", async () => {
    const wrapper = await render(task(), {
      reports: [
        report({
          source: "agent_reported",
          checks: [{ name: "claimed", exit_code: 0 }],
        }),
      ],
    });

    const cell = wrapper
      .get('[data-testid="verification"]')
      .findAll("tbody td")[1];
    expect(cell.classes()).not.toContain("machine");
  });

  it("shows both accounts of a disagreement and takes no side", async () => {
    const wrapper = await render(task(), {
      evidence: [
        {
          id: "e1",
          kind: "agent_finding",
          source: "agent_reported",
          payload: {},
          run_id: null,
          written_by_kind: "agent",
          collected_at: "2026-08-14T00:00:00Z",
        },
        {
          id: "e2",
          kind: "changed_files",
          source: "machine_verified",
          payload: {},
          run_id: null,
          written_by_kind: "agent",
          collected_at: "2026-08-14T00:00:01Z",
        },
      ],
    });

    const list = wrapper.get('[data-testid="evidence"]');
    expect(list.findAll("li")).toHaveLength(2);
    const note = wrapper.get('[data-testid="disagreement"]').text();
    expect(note).toContain("平台不判斷哪一份對");
    // No verdict anywhere: adding one would be a judgement nobody is accountable for.
    expect(wrapper.text()).not.toContain("以機器事實為準");
  });

  it("keeps the forced-done mark permanently visible and outside any disclosure", async () => {
    const wrapper = await render(
      task({
        stage: "done",
        force_done_at: "2026-08-14T00:00:00Z",
        force_done_reason: "verification host is down",
      }),
    );

    const mark = wrapper.get('[data-testid="forced-done"]');
    expect(mark.text()).toContain("強制推進");
    expect(mark.text()).toContain("verification host is down");
    // Not collapsible, and there is no control that clears it: the only way out is to
    // move the card out of `done` (ADR 0033 §5).
    expect(mark.html()).not.toContain("<details");
    expect(wrapper.text()).not.toContain("清除");
  });
});
