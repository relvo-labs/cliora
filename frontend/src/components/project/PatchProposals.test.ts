/**
 * Document patch proposals (RQ-10 §7, FR-SPEC-007, exit condition 22).
 *
 * The first test is the phase's only stored-XSS assertion, and it belongs here rather
 * than in the backend: the server stores a string, and the place it can hurt somebody is
 * the render — a single-origin deployment makes "display this" and "run this" the same
 * act unless the render is a text node (ADR 0020, ADR 0030 Part B).
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "../../api/client";
import type { DocumentPatchProposal } from "../../api/dto";
import PatchProposals from "./PatchProposals.vue";

function proposal(
  over: Partial<DocumentPatchProposal> = {},
): DocumentPatchProposal {
  return {
    id: "d1",
    project_id: "p1",
    requirement_id: null,
    run_id: null,
    seq: 3,
    target_path: "docs/prd.md",
    diff: "--- a/docs/prd.md\n+++ b/docs/prd.md\n@@\n-old\n+new\n",
    sections: { modified_sections: ["§8.4"] },
    reason: "程式碼與描述不符",
    related_task_ids: [],
    open_questions: [],
    status: "pending",
    decided_by: null,
    decided_at: null,
    decision_note: null,
    created_at: "2026-08-14T00:00:00Z",
    ...over,
  };
}

function client(rows: DocumentPatchProposal[]) {
  return {
    listPatchProposals: vi.fn().mockResolvedValue(rows),
    decidePatchProposal: vi.fn().mockResolvedValue(rows[0]),
  } as unknown as ApiClient;
}

async function render(rows: DocumentPatchProposal[], canDecide = true) {
  const api = client(rows);
  const wrapper = mount(PatchProposals, {
    props: { client: api, projectId: "p1", canDecide },
  });
  await vi.waitFor(() =>
    expect(
      (api.listPatchProposals as ReturnType<typeof vi.fn>).mock.calls.length,
    ).toBe(1),
  );
  await wrapper.vm.$nextTick();
  return { wrapper, api };
}

describe("patch proposals", () => {
  it("renders a diff as text, never as markup", async () => {
    // The payload is agent-produced and arrives in the application's own origin. If this
    // ever renders as markup, the platform has become a stored-XSS channel for the one
    // kind of content it least controls.
    const hostile =
      "--- a/x\n+++ b/x\n+<script>window.__pwned = 1</" + "script>\n";
    const { wrapper } = await render([proposal({ diff: hostile })]);
    await wrapper.get("[data-toggle='3']").trigger("click");

    const block = wrapper.get("[data-diff='3']");
    expect(block.text()).toContain("<script>");
    // The assertion that matters: the tag is *text inside* the block, not an element.
    expect(block.element.querySelector("script")).toBeNull();
    expect(block.element.children).toHaveLength(0);
    expect(
      (window as unknown as Record<string, unknown>).__pwned,
    ).toBeUndefined();
  });

  it("offers no way to download or apply the patch", async () => {
    // A downloadable `.patch` relocates applying to a terminal, where none of this
    // phase's gates exist. The friction of copying text is the control.
    const { wrapper } = await render([proposal()]);
    expect(wrapper.find("a[download]").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("下載");
    expect(wrapper.text()).toContain("不套用");
  });

  it("says that accepting creates nothing", async () => {
    const { wrapper, api } = await render([proposal()]);
    expect(wrapper.text()).toContain("接受只記錄決定");
    await wrapper.get("[data-accept='3']").trigger("click");
    expect(api.decidePatchProposal).toHaveBeenCalledWith("d1", true, undefined);
  });

  it("will not reject without a reason", async () => {
    const { wrapper, api } = await render([proposal()]);
    await wrapper.get("[data-open-reject='3']").trigger("click");
    expect(
      wrapper.get("[data-confirm-reject='3']").attributes("disabled"),
    ).toBeDefined();
    await wrapper.get("[data-reject='3']").setValue("PRD 本來就是對的");
    await wrapper.get("[data-confirm-reject='3']").trigger("click");
    expect(api.decidePatchProposal).toHaveBeenCalledWith(
      "d1",
      false,
      "PRD 本來就是對的",
    );
  });

  it("shows unresolved questions without blocking acceptance", async () => {
    // Unlike a specification's: approving a specification unlocks decomposition, while
    // accepting a patch proposal unlocks nothing. Asymmetric gates, asymmetric reason.
    const { wrapper } = await render([
      proposal({
        open_questions: [{ id: "q1", question: "§8.5 要不要一起改？" }],
      }),
    ]);
    expect(wrapper.get("[data-patch-questions]").text()).toContain("§8.5");
    expect(
      wrapper.get("[data-accept='3']").attributes("disabled"),
    ).toBeUndefined();
  });

  it("hides the decision controls from someone without the action", async () => {
    const { wrapper } = await render([proposal()], false);
    expect(wrapper.find("[data-accept='3']").exists()).toBe(false);
    expect(wrapper.find("[data-open-reject='3']").exists()).toBe(false);
    // But the content is still readable: the queue is part of the shape of the project.
    expect(wrapper.text()).toContain("docs/prd.md");
  });
});
