import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { Task, WorkItemCard } from "../../api/dto";
import InlineTitleEdit from "./components/InlineTitleEdit.vue";
import TaskPropertySidebar from "./components/TaskPropertySidebar.vue";

// The Drawer's two behaviours that are silent when wrong (PX-39/PX-40).
//
//   * **A conflict keeps the draft, word for word.** Losing a paragraph because somebody
//     else changed the card's risk is the failure this component exists to prevent.
//   * **An execution setting that is the reason the card is stuck expands itself, and says
//     which one.** Progressive disclosure is fine until the hidden thing is the answer.

const { updateTask } = vi.hoisted(() => ({ updateTask: vi.fn() }));

vi.mock("../../stores/auth", () => ({
  api: () => ({ updateTask }),
  useAuthStore: () => ({ hasPermission: () => true, hasFeature: () => true }),
}));

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: "t-1",
    project_id: "p-1",
    card_ref: "TK-1",
    title: "支援 SAML SSO 登入",
    description: "使用者要能用公司的 IdP 登入。",
    objective: null,
    scope: null,
    non_goals: null,
    stage: "implementing",
    risk: "high",
    priority: "high",
    owner_user_id: null,
    assigned_runner_id: null,
    required_labels: [],
    readiness: {},
    gates: {},
    acceptance_criteria: [],
    links: {},
    version: 4,
    source: "repo",
    repository_id: null,
    base_branch: null,
    delivery: "pull_request",
    target_branch: null,
    existing_pr_ref: null,
    required_secrets: [],
    verification_commands: [],
    force_done_reason: null,
    force_done_by: null,
    force_done_at: null,
    requirement_id: null,
    epic_id: null,
    user_story_id: null,
    card_kind: "implementation",
    created_at: "2026-08-23T00:00:00Z",
    updated_at: "2026-08-23T00:00:00Z",
    ...overrides,
  } as Task;
}

function card(overrides: Partial<WorkItemCard> = {}): WorkItemCard {
  return {
    id: "t-1",
    card_ref: "TK-1",
    project_id: "p-1",
    version: 4,
    updated_at: "2026-08-23T00:00:00Z",
    ...overrides,
  };
}

describe("InlineTitleEdit", () => {
  it("saves only on the button, and marks itself dirty first", async () => {
    // Explicit save with a dirty indicator, never autosave: a field that sometimes saves
    // itself and sometimes waits is a field nobody trusts.
    updateTask.mockReset().mockResolvedValue({ task: task(), warnings: [] });
    const wrapper = mount(InlineTitleEdit, {
      props: { task: task(), canEdit: true },
    });
    expect(wrapper.find("[data-dirty]").exists()).toBe(false);
    await wrapper.get("[data-title-input]").setValue("支援 SAML 與 OIDC");
    expect(wrapper.get("[data-dirty]").text()).toBe("未儲存");
    expect(updateTask).not.toHaveBeenCalled();
    await wrapper.get("[data-save]").trigger("click");
    expect(updateTask).toHaveBeenCalledOnce();
  });

  it("keeps the draft word for word after a 409", async () => {
    // **The test the ticket is about.** The input's contents must be byte-identical
    // afterwards; `details.current` is the server's card, so "compare" needs no second
    // request.
    const { ApiError } = await import("../../api/client");
    updateTask.mockReset().mockRejectedValue(
      new ApiError("TASK_VERSION_CONFLICT", "conflict", 409, undefined, {
        current: task({ version: 9, title: "別人改的標題" }),
      }),
    );
    const draft = "我正在寫的一段很長的說明，還沒寫完";
    const wrapper = mount(InlineTitleEdit, {
      props: { task: task(), canEdit: true },
    });
    await wrapper.get("[data-description-input]").setValue(draft);
    await wrapper.get("[data-save]").trigger("click");
    await wrapper.vm.$nextTick();

    expect(wrapper.find("[data-conflict]").exists()).toBe(true);
    expect(
      (wrapper.get("[data-description-input]").element as HTMLTextAreaElement)
        .value,
    ).toBe(draft);
    // Both recoveries are offered, and comparing needs no follow-up request.
    expect(wrapper.find("[data-conflict-reload]").exists()).toBe(true);
    expect(wrapper.find("[data-conflict-keep]").exists()).toBe(true);
    expect(wrapper.get("[data-conflict-compare]").text()).toContain(
      "別人改的標題",
    );
  });

  it("puts a field error beside the field, not only in a toast", async () => {
    // A toast is gone before somebody has finished reading the sentence they were typing.
    const { ApiError } = await import("../../api/client");
    updateTask
      .mockReset()
      .mockRejectedValue(new ApiError("VALIDATION", "太長了", 422));
    const wrapper = mount(InlineTitleEdit, {
      props: { task: task(), canEdit: true },
    });
    await wrapper.get("[data-title-input]").setValue("x");
    await wrapper.get("[data-save]").trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.get("[data-field-error]").text()).toBe("太長了");
  });

  it("offers no save control to a reader", () => {
    const wrapper = mount(InlineTitleEdit, {
      props: { task: task(), canEdit: false },
    });
    expect(wrapper.find("[data-save]").exists()).toBe(false);
  });
});

describe("TaskPropertySidebar: the execution block opens itself", () => {
  // Four situations, one test each (plan/26/07 §2 — the exit condition asks for exactly
  // this). Each names a *different* row, because "expand this" without "because of this"
  // makes a reader read all eight.
  it("opens for no eligible runner and points at the labels", () => {
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task(),
        card: card({ primary_attention: "no_eligible_runner" }),
      },
    });
    expect(wrapper.get("[data-execution-block]").attributes("data-open")).toBe(
      "true",
    );
    expect(wrapper.get("[data-execution-reason]").text()).toContain("必要標籤");
  });

  it("opens for an offline assigned runner and points at the assignment", () => {
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task(),
        card: card({ primary_attention: "assigned_runner_offline" }),
      },
    });
    expect(wrapper.get("[data-execution-reason]").text()).toContain(
      "指定 Agent",
    );
  });

  it("opens for a blocked card that declares a secret", () => {
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task({ required_secrets: ["NPM_TOKEN"] }),
        card: card({ is_blocked: true }),
      },
    });
    expect(wrapper.get("[data-execution-reason]").text()).toContain("機密");
  });

  it("opens when a delivery is declared with no repository bound", () => {
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task({ repository_id: null, delivery: "pull_request" }),
        card: card(),
      },
    });
    expect(wrapper.get("[data-execution-reason]").text()).toContain("程式庫");
  });

  it("stays collapsed and silent when nothing is wrong", () => {
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task({
          repository_id: "r-1",
          delivery: "none",
          required_secrets: [],
        }),
        card: card({ primary_attention: null }),
      },
    });
    expect(wrapper.get("[data-execution-block]").attributes("data-open")).toBe(
      "false",
    );
    expect(wrapper.find("[data-execution-reason]").exists()).toBe(false);
  });

  it("does not re-derive the reason from other fields", () => {
    // It reads `primary_attention` and `blocking_reason`. A sidebar that worked out "no
    // eligible runner" for itself would be a second implementation of the one thing
    // `derive_attention` is (ADR 0040 §3).
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        // Every ingredient of "no eligible runner" is here — a tag nothing carries and no
        // runner — and the server did not say so, so neither does the sidebar.
        task: task({
          required_labels: ["arm64"],
          repository_id: "r-1",
          delivery: "none",
        }),
        card: card({ primary_attention: null }),
      },
    });
    expect(wrapper.find("[data-execution-reason]").exists()).toBe(false);
  });
});

// --- the phone layout (PX-46) -------------------------------------------------------

describe("TaskPropertySidebar on a narrow screen", () => {
  /** Pin `matchMedia` to a width. jsdom has none, which is also why the component guards
   *  for its absence — a sidebar that throws on mount is worse than one that assumes a
   *  wide screen. */
  function withWidth(narrow: boolean): void {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      configurable: true,
      value: (query: string) => ({
        matches: narrow,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    });
  }

  it("collapses into one line on a phone", () => {
    // Below 760px the Drawer is one column, so the sidebar lands *under* the conversation.
    // Eight rows of properties between the reader and the composer is why this collapses.
    //
    // `delivery: "none"` because the default fixture declares a pull request with no
    // repository, which is one of the four situations that force the block open — and a
    // forced-open card keeps the properties visible on purpose (the last test here).
    withWidth(true);
    const wrapper = mount(TaskPropertySidebar, {
      props: { task: task({ delivery: "none" }), card: card() },
    });
    expect(wrapper.find("[data-properties-toggle]").exists()).toBe(true);
    expect(wrapper.find("dl.properties").exists()).toBe(false);
  });

  it("expands when the reader asks", async () => {
    withWidth(true);
    const wrapper = mount(TaskPropertySidebar, {
      props: { task: task({ delivery: "none" }), card: card() },
    });
    await wrapper.get("[data-properties-toggle]").trigger("click");
    expect(wrapper.find("dl.properties").exists()).toBe(true);
  });

  it("stays open on a wide screen, with no accordion at all", () => {
    // The reason this is `matchMedia` and not CSS: a stylesheet cannot force a collapsed
    // section open, so a media query alone would leave desktop readers opening it every
    // time.
    withWidth(false);
    const wrapper = mount(TaskPropertySidebar, {
      props: { task: task(), card: card() },
    });
    expect(wrapper.find("[data-properties-toggle]").exists()).toBe(false);
    expect(wrapper.find("dl.properties").exists()).toBe(true);
  });

  it("the forced-open rule still wins on a phone", () => {
    // The reason hiding a setting is acceptable is that it stops being hidden when it is
    // the answer. That has to hold on the screen where hiding is most aggressive.
    withWidth(true);
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task(),
        card: card({ primary_attention: "no_eligible_runner" }),
      },
    });
    expect(wrapper.find("dl.properties").exists()).toBe(true);
    expect(wrapper.get("[data-execution-block]").attributes("data-open")).toBe(
      "true",
    );
  });
});

// --- the signal set, not the primary (PX-39, found by wave 5's browser run) ----------

describe("TaskPropertySidebar reads the signal set", () => {
  it("opens for a situation that is not the winning badge", () => {
    // **The bug this replaces.** A card that has no eligible runner *and* is awaiting a
    // human decision badges as `pending_human_approval`, because that outranks it (D107).
    // Reading `primary_attention` left the execution block collapsed on exactly the card
    // whose execution settings were the answer — the situation was true, the block stayed
    // shut, and the interface refused to say why.
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task({ delivery: "none" }),
        card: card({ primary_attention: "pending_human_approval" }),
        attention: {
          task_id: "t-1",
          primary: "pending_human_approval",
          signals: ["pending_human_approval", "no_eligible_runner"],
          runtime_signals_available: true,
        },
      },
    });
    expect(wrapper.get("[data-execution-block]").attributes("data-open")).toBe(
      "true",
    );
    expect(wrapper.get("[data-execution-reason]").text()).toContain("必要標籤");
  });

  it("falls back to the primary when the set has not arrived", () => {
    // The primary is a true statement about the card, just an incomplete one — and a
    // block that stayed shut until a second request resolved would flicker open under the
    // reader's cursor.
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task({ delivery: "none" }),
        card: card({ primary_attention: "assigned_runner_offline" }),
        attention: null,
      },
    });
    expect(wrapper.get("[data-execution-block]").attributes("data-open")).toBe(
      "true",
    );
    expect(wrapper.get("[data-execution-reason]").text()).toContain(
      "指定的 Agent 離線",
    );
  });

  it("stays quiet when nothing in the set is one of the four", () => {
    const wrapper = mount(TaskPropertySidebar, {
      props: {
        task: task({ delivery: "none" }),
        card: card({ primary_attention: "over_wip_or_stale" }),
        attention: {
          task_id: "t-1",
          primary: "over_wip_or_stale",
          signals: ["over_wip_or_stale", "dependency_blocked"],
          runtime_signals_available: true,
        },
      },
    });
    expect(wrapper.get("[data-execution-block]").attributes("data-open")).toBe(
      "false",
    );
    expect(wrapper.find("[data-execution-reason]").exists()).toBe(false);
  });
});
