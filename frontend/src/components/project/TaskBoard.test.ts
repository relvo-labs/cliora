import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { Board } from "../../api/dto";
import TaskBoard from "./TaskBoard.vue";

/**
 * The board's interaction contract (`plan/17/07-…md` §2.2), which is one sentence:
 * move optimistically, and on **any** refusal put the card back and say something
 * specific. A card left in its new lane after a failure is a card the user believes
 * moved — and the version conflict that produced it is exactly the case where two
 * people are looking at the same board.
 */

const LANES = [
  { stage: "backlog", label: "待辦", wip_suggested: null },
  { stage: "blocked", label: "阻塞", wip_suggested: null },
  { stage: "ready", label: "就緒", wip_suggested: 2 },
  { stage: "implementing", label: "進行中", wip_suggested: 3 },
  { stage: "verify", label: "驗證中", wip_suggested: 3 },
  { stage: "done", label: "完成", wip_suggested: null },
] as const;

function board(
  cards: Partial<Board["lanes"][number]["cards"][number]>[],
): Board {
  const filled = cards.map((card, index) => ({
    id: card.id ?? `id-${index}`,
    card_ref: card.card_ref ?? `TASK-${index + 1}`,
    title: card.title ?? "card",
    stage: card.stage ?? "backlog",
    risk: card.risk ?? "medium",
    priority: "normal",
    owner_user_id: null,
    owner_name: null,
    delivery: card.delivery ?? "pull_request",
    blocking_count: card.blocking_count ?? 0,
    gates_approved_count: 0,
    version: card.version ?? 1,
    updated_at: "2026-08-09T00:00:00Z",
  })) as Board["lanes"][number]["cards"];
  return {
    lanes: LANES.map((lane) => ({
      ...lane,
      count: filled.filter((card) => card.stage === lane.stage).length,
      cards: filled.filter((card) => card.stage === lane.stage),
    })) as Board["lanes"],
    has_more: false,
  };
}

function client(overrides: Record<string, unknown> = {}) {
  return { updateTask: vi.fn().mockResolvedValue({}), ...overrides } as never;
}

describe("TaskBoard", () => {
  it("groups cards into the six lanes in order", () => {
    const wrapper = mount(TaskBoard, {
      props: {
        board: board([{ stage: "backlog" }, { stage: "done" }]),
        client: client(),
        canWrite: true,
      },
    });
    const lanes = wrapper.findAll("[data-stage]");
    expect(lanes.map((lane) => lane.attributes("data-stage"))).toEqual([
      "backlog",
      "blocked",
      "ready",
      "implementing",
      "verify",
      "done",
    ]);
  });

  it("flags a lane over its WIP advice without refusing anything", () => {
    // Monstrare's semantics: the count changes colour and nothing is blocked.
    const wrapper = mount(TaskBoard, {
      props: {
        board: board([
          { stage: "ready", id: "a" },
          { stage: "ready", id: "b" },
          { stage: "ready", id: "c" },
        ]),
        client: client(),
        canWrite: true,
      },
    });
    const ready = wrapper.find('[data-stage="ready"] .count');
    expect(ready.attributes("data-over-wip")).toBe("true");
    expect(wrapper.findAll('[data-stage="ready"] .card')).toHaveLength(3);
  });

  it("moves a card optimistically and sends the version it was read at", async () => {
    const updateTask = vi.fn().mockResolvedValue({});
    const wrapper = mount(TaskBoard, {
      props: {
        board: board([{ id: "x", card_ref: "TASK-1", version: 7 }]),
        client: client({ updateTask }),
        canWrite: true,
      },
    });
    await wrapper.find('[data-move-for="TASK-1"]').trigger("click");
    await wrapper.find('[data-move-to="ready"]').trigger("click");
    expect(updateTask).toHaveBeenCalledWith("x", {
      version: 7,
      stage: "ready",
    });
    // Optimistic: the card is in its new lane before the promise settles.
    expect(wrapper.find('[data-stage="ready"] .card').exists()).toBe(true);
  });

  it("puts the card back and names the blocking cards when the move is refused", async () => {
    const updateTask = vi.fn().mockRejectedValue(
      new ApiError("TASK_DEPENDENCY_UNSATISFIED", "blocked", 409, undefined, {
        blocking_refs: ["TASK-3", "TASK-7"],
      }),
    );
    const wrapper = mount(TaskBoard, {
      props: {
        board: board([{ id: "x", card_ref: "TASK-1" }]),
        client: client({ updateTask }),
        canWrite: true,
      },
    });
    await wrapper.find('[data-move-for="TASK-1"]').trigger("click");
    await wrapper.find('[data-move-to="implementing"]').trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 0));

    const message = wrapper.find("[data-board-message]");
    expect(message.text()).toContain("TASK-3");
    expect(message.text()).toContain("TASK-7");
    // Back in backlog: the rollback is the property, the message is the courtesy.
    expect(wrapper.find('[data-stage="backlog"] .card').exists()).toBe(true);
    expect(wrapper.find('[data-stage="implementing"] .card').exists()).toBe(
      false,
    );
  });

  it("says a card was changed by someone else on a version conflict", async () => {
    const updateTask = vi
      .fn()
      .mockRejectedValue(
        new ApiError("TASK_VERSION_CONFLICT", "conflict", 409),
      );
    const wrapper = mount(TaskBoard, {
      props: {
        board: board([{ id: "x", card_ref: "TASK-1" }]),
        client: client({ updateTask }),
        canWrite: true,
      },
    });
    await wrapper.find('[data-move-for="TASK-1"]').trigger("click");
    await wrapper.find('[data-move-to="ready"]').trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wrapper.find("[data-board-message]").text()).toContain("別人改過");
    expect(wrapper.find('[data-stage="backlog"] .card').exists()).toBe(true);
  });

  it("offers no move control to a reader", () => {
    const wrapper = mount(TaskBoard, {
      props: {
        board: board([{ card_ref: "TASK-1" }]),
        client: client(),
        canWrite: false,
      },
    });
    expect(wrapper.find('[data-move-for="TASK-1"]').exists()).toBe(false);
  });
});
