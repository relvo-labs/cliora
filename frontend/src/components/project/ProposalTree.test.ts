/**
 * The acceptance surface (RQ-10, FR-SPEC-005).
 *
 * Each test here defends something the JSON textarea it replaced could not express, and
 * two of them defend a *number* rather than a behaviour — the pull-request count and the
 * backlog count — because those are what make a person stop before accepting thirty-eight
 * cards.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { TaskProposal } from "../../api/dto";
import ProposalTree from "./ProposalTree.vue";

const READINESS = [
  "problem_stated",
  "acceptance_criteria",
  "scope_bounded",
  "dependencies_known",
  "verification_defined",
  "risk_assessed",
  "context_pointers",
];

function full(): Record<string, boolean> {
  return Object.fromEntries(READINESS.map((key) => [key, true]));
}

function proposal(
  tree: Record<string, unknown>,
  accepted: string[] = [],
): TaskProposal {
  const ids = ((tree.tasks as Array<{ id: string }>) ?? []).map(
    (task) => task.id,
  );
  return {
    id: "p1",
    seq: 1,
    spec_id: null,
    tree,
    status: accepted.length ? "partially_accepted" : "pending",
    decided_by: null,
    decided_at: null,
    decision_note: null,
    run_id: null,
    created_at: "2026-08-14T00:00:00Z",
    accepted_item_ids: accepted,
    remaining_item_ids: ids.filter((id) => !accepted.includes(id)),
  };
}

function render(
  tree: Record<string, unknown>,
  accepted: string[] = [],
  canDecide = true,
) {
  return mount(ProposalTree, {
    props: {
      proposal: proposal(tree, accepted),
      readinessKeys: READINESS,
      canDecide,
    },
    global: { stubs: { RouterLink: true } },
  });
}

describe("proposal tree", () => {
  it("groups by epic and story without offering a checkbox for either", async () => {
    // Accepting sets `epic_id` and `user_story_id` to null, so a checkbox on those rows
    // would do nothing. A control that does nothing is worse than no control.
    const wrapper = render({
      epics: [{ id: "e1", title: "報表匯出" }],
      user_stories: [{ id: "u1", epic_id: "e1", title: "選擇格式" }],
      tasks: [
        { id: "t1", user_story_id: "u1", title: "後端", readiness: full() },
      ],
    });
    expect(wrapper.text()).toContain("報表匯出");
    expect(wrapper.text()).toContain("選擇格式");
    expect(wrapper.findAll("input[type=checkbox]")).toHaveLength(1);
    expect(wrapper.text()).toContain("只用於分組");
  });

  it("shows what a card is missing and still lets it be selected", async () => {
    // Landing in the backlog is the design, not an error — so the count is shown before
    // the click rather than explained after it.
    const wrapper = render({
      tasks: [
        { id: "t1", title: "半成品", readiness: { problem_stated: true } },
      ],
    });
    const badge = wrapper.get("[data-item='t1']");
    expect(await badge.attributes("disabled")).toBeUndefined();
    expect(wrapper.text()).toContain("DoR 1/7");
    expect(wrapper.text()).toContain("會建立在「待辦」");
  });

  it("counts pull-request cards on their own line", async () => {
    // One acceptance can produce six outward-facing branches. Folded into the total,
    // that number is invisible at the moment it matters (plan/22/README §5.1).
    const wrapper = render({
      tasks: [
        { id: "t1", title: "a", readiness: full(), delivery: "pull_request" },
        { id: "t2", title: "b", readiness: full(), delivery: "pull_request" },
        { id: "t3", title: "c", readiness: full(), delivery: "artifact" },
      ],
    });
    for (const id of ["t1", "t2", "t3"]) {
      await wrapper.get(`[data-item='${id}']`).setValue(true);
    }
    expect(wrapper.get("[data-proposal-summary]").text()).toContain(
      "將建立 3 張卡片",
    );
    expect(wrapper.get("[data-pr-count]").text()).toContain("2");
  });

  it("warns when a selected card depends on one that is not selected", async () => {
    const wrapper = render({
      tasks: [
        { id: "base", title: "基礎", readiness: full() },
        { id: "dep", title: "依賴", readiness: full(), depends_on: ["base"] },
      ],
    });
    await wrapper.get("[data-item='dep']").setValue(true);
    expect(wrapper.get("[data-proposal-summary]").text()).toContain(
      "相依指向沒被勾選的卡片",
    );
    // And selecting the other end clears it.
    await wrapper.get("[data-item='base']").setValue(true);
    expect(wrapper.get("[data-proposal-summary]").text()).not.toContain(
      "相依指向沒被勾選的卡片",
    );
  });

  it("marks already-created items and does not offer them again", async () => {
    const wrapper = render(
      { tasks: [{ id: "t1", title: "已建立", readiness: full() }] },
      ["t1"],
    );
    expect(
      wrapper.get("[data-item='t1']").attributes("disabled"),
    ).toBeDefined();
    expect(wrapper.text()).toContain("已建立");
  });

  it("sends only the overrides for items being accepted", async () => {
    // The server refuses an override for an unselected item; sending one anyway turns a
    // deliberate refusal into a confusing one.
    const wrapper = render({
      tasks: [
        { id: "t1", title: "a", readiness: full(), delivery: "pull_request" },
        { id: "t2", title: "b", readiness: full(), delivery: "pull_request" },
      ],
    });
    await wrapper.get("[data-edit='t2']").trigger("click");
    await wrapper.get("[data-override='t2.delivery']").setValue("artifact");
    await wrapper.get("[data-item='t1']").setValue(true);
    await wrapper.get("[data-accept-proposal]").trigger("click");

    const emitted = wrapper.emitted("accept");
    expect(emitted).toBeTruthy();
    const payload = emitted![0][0] as {
      acceptIds: string[];
      overrides: Record<string, unknown>;
    };
    expect(payload.acceptIds).toEqual(["t1"]);
    expect(payload.overrides).toEqual({});
  });

  it("offers no way to edit readiness", async () => {
    // Ticking it here would turn "a card missing readiness lands in backlog" into a rule
    // that disappears whenever it is inconvenient.
    const wrapper = render({
      tasks: [{ id: "t1", title: "a", readiness: { problem_stated: true } }],
    });
    await wrapper.get("[data-edit='t1']").trigger("click");
    expect(wrapper.find("[data-override='t1.readiness']").exists()).toBe(false);
    expect(wrapper.text()).toContain("就緒條件由拆解填寫");
  });

  it("an override changes the counts it feeds", async () => {
    const wrapper = render({
      tasks: [
        { id: "t1", title: "a", readiness: full(), delivery: "pull_request" },
      ],
    });
    await wrapper.get("[data-item='t1']").setValue(true);
    expect(wrapper.find("[data-pr-count]").exists()).toBe(true);
    await wrapper.get("[data-edit='t1']").trigger("click");
    await wrapper.get("[data-override='t1.delivery']").setValue("artifact");
    expect(wrapper.find("[data-pr-count]").exists()).toBe(false);
  });

  it("will not reject without a reason", async () => {
    const wrapper = render({
      tasks: [{ id: "t1", title: "a", readiness: full() }],
    });
    await wrapper.get("[data-open-reject]").trigger("click");
    expect(
      wrapper.get("[data-confirm-reject]").attributes("disabled"),
    ).toBeDefined();
    await wrapper.get("[data-reject-note]").setValue("這批卡太細");
    expect(
      wrapper.get("[data-confirm-reject]").attributes("disabled"),
    ).toBeUndefined();
    await wrapper.get("[data-confirm-reject]").trigger("click");
    expect(wrapper.emitted("reject")![0]).toEqual(["這批卡太細"]);
  });

  it("hides every control from someone who cannot decide", () => {
    const wrapper = render(
      { tasks: [{ id: "t1", title: "a", readiness: full() }] },
      [],
      false,
    );
    expect(wrapper.find("[data-proposal-summary]").exists()).toBe(false);
    expect(
      wrapper.get("[data-item='t1']").attributes("disabled"),
    ).toBeDefined();
  });
});
