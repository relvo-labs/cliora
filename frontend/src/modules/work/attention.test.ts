import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import AttentionBadge from "./components/AttentionBadge.vue";
import { ATTENTION, ATTENTION_LEVELS, isAttentionLevel } from "./attention";

/** The order the server publishes. Restated here, not imported, because the point of
 *  the assertion is that the two agree — importing it would make the test tautological.
 *  The backend's copy is `ATTENTION_ORDER` in `services/work/attention.py`, and its own
 *  test pins it to the same eight strings. */
const SERVER_ORDER = [
  "waiting_for_your_input",
  "pending_human_approval",
  "verification_failed",
  "run_failed",
  "no_eligible_runner",
  "assigned_runner_offline",
  "dependency_blocked",
  "over_wip_or_stale",
];

describe("attention vocabulary", () => {
  it("knows exactly the eight levels the server can send", () => {
    expect([...ATTENTION_LEVELS]).toEqual(SERVER_ORDER);
    expect(Object.keys(ATTENTION).sort()).toEqual([...SERVER_ORDER].sort());
  });

  it("drops a level this build does not know instead of drawing a blank badge", () => {
    // A ninth level added server-side must degrade to the card looking the way it did
    // before the level existed — not to an empty coloured rectangle.
    expect(isAttentionLevel("a_level_from_the_future")).toBe(false);
    const wrapper = mount(AttentionBadge, {
      props: { primary: "a_level_from_the_future" },
    });
    expect(wrapper.find("[data-attention]").exists()).toBe(false);
  });
});

describe("AttentionBadge carries more than colour", () => {
  // research/style.md §22: every attention badge must have at least two cues besides
  // colour. This asserts three for all eight levels — a non-empty accessible name that
  // is a whole sentence, a glyph, and a variant class that differs by shape.
  it.each(ATTENTION_LEVELS)("%s has a label, a glyph and a shape", (level) => {
    const wrapper = mount(AttentionBadge, { props: { primary: level } });
    const badge = wrapper.get("[data-attention]");

    const name = badge.attributes("aria-label") ?? "";
    expect(name.length).toBeGreaterThan(2);
    expect(name).toBe(ATTENTION[level].label);
    // The name is a statement about the card, not a severity word. "注意" and "警告"
    // tell a reader nothing they can act on.
    expect(["注意", "警告", "錯誤"]).not.toContain(name);

    expect(badge.get(".glyph").text().length).toBeGreaterThan(0);
    expect(badge.get(".label").text()).toBe(ATTENTION[level].label);
    expect(
      badge
        .classes()
        .some((name) => name === "v-solid" || name === "v-outline"),
    ).toBe(true);
    expect(badge.classes()).toContain(`t-${ATTENTION[level].tone}`);
  });

  it("gives the two levels somebody is waiting on a different shape from the rest", () => {
    const solid = ATTENTION_LEVELS.filter(
      (level) => ATTENTION[level].variant === "solid",
    );
    expect(solid).toEqual(["waiting_for_your_input", "pending_human_approval"]);
  });

  it("uses five colours for eight levels, sharing by what clears them", () => {
    const tones: Record<string, string[]> = {};
    for (const level of ATTENTION_LEVELS) {
      (tones[ATTENTION[level].tone] ??= []).push(level);
    }
    expect(Object.keys(tones).sort()).toEqual([
      "attention-approval",
      "attention-blocked",
      "attention-failed",
      "attention-human",
      "attention-warning",
    ]);
    // The two failure levels are one action: go and look at why it broke.
    expect(tones["attention-failed"]).toEqual([
      "verification_failed",
      "run_failed",
    ]);
  });

  it("shortens the label under the compact density without abbreviating the name", () => {
    const compact = mount(AttentionBadge, {
      props: { primary: "no_eligible_runner", density: "compact" },
    });
    expect(compact.get(".label").text()).toBe("無可用 Agent");
    // The accessible name stays the full sentence: density is a visual preference and
    // must not shorten what a screen reader is told.
    expect(compact.get("[data-attention]").attributes("aria-label")).toBe(
      "沒有符合條件的 Agent",
    );
  });

  it("shows the other signals as a count and says so in the accessible name", () => {
    const wrapper = mount(AttentionBadge, {
      props: { primary: "run_failed", count: 3 },
    });
    expect(wrapper.get(".extra").text()).toBe("＋2");
    expect(wrapper.get("[data-attention]").attributes("aria-label")).toBe(
      "執行失敗，另有 2 項",
    );
  });

  it("shows no count when the primary is the only signal", () => {
    const wrapper = mount(AttentionBadge, {
      props: { primary: "run_failed", count: 1 },
    });
    expect(wrapper.find(".extra").exists()).toBe(false);
  });
});
