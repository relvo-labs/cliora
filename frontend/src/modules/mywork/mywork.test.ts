import { mount } from "@vue/test-utils";
import { createRouter, createWebHistory, type Router } from "vue-router";
import { describe, expect, it } from "vitest";

import AttentionSection from "./components/AttentionSection.vue";
import {
  encodeFilter,
  sectionsFor,
  sevenDaysAgo,
  type SectionResult,
} from "./sections";

// My Work's one genuinely tricky property, and the section specs that feed it.
//
// **A section has three states, not two.** The "no eligible runner" section depends on
// the node registry, which is a dict in the Central process (ADR 0029 §1), and when it
// cannot be consulted the honest answer is "we did not look". Rendering that as an empty
// list is the failure: **"none" sends a person to do something else, and "we do not know"
// sends them to reload**, and only one of those is right.

function router(): Router {
  const blank = { template: "<div/>" };
  return createRouter({
    history: createWebHistory(),
    routes: [
      // A catch-all as well as the one route under test: `createWebHistory` starts at the
      // jsdom location, and an unmatched start warns on every mount.
      { path: "/:pathMatch(.*)*", component: blank },
      { path: "/projects/:id/work", name: "project-work", component: blank },
    ],
  });
}

function card(overrides: Record<string, unknown> = {}) {
  return {
    id: "t-1",
    card_ref: "TK-1",
    project_id: "p-1",
    version: 1,
    updated_at: "2026-08-23T00:00:00Z",
    title: "支援 SAML SSO 登入",
    primary_attention: "waiting_for_your_input",
    attention_count: 2,
    ...overrides,
  };
}

function section(overrides: Partial<SectionResult> = {}): SectionResult {
  const [spec] = sectionsFor("u-1");
  return {
    spec,
    items: [card()],
    count: 1,
    unavailable: null,
    ...overrides,
  } as SectionResult;
}

function render(result: SectionResult) {
  return mount(AttentionSection, {
    props: { section: result },
    global: { plugins: [router()] },
  });
}

describe("AttentionSection: the three states", () => {
  it("shows the cards and the server's count when it has an answer", () => {
    const wrapper = render(section({ count: 12 }));
    // The count is the server's, not `items.length`: this page loads ten per section.
    expect(wrapper.get("[data-count]").text()).toBe("12");
    expect(wrapper.get("[data-card='TK-1']").text()).toContain(
      "支援 SAML SSO 登入",
    );
    expect(wrapper.find("[data-empty]").exists()).toBe(false);
    expect(wrapper.find("[data-unavailable]").exists()).toBe(false);
  });

  it("says there is nothing when there is nothing", () => {
    const wrapper = render(section({ items: [], count: 0 }));
    expect(wrapper.get("[data-empty]").text()).toContain("沒有等你的事");
    expect(wrapper.find("[data-unavailable]").exists()).toBe(false);
  });

  it("says it could not answer rather than answering zero", () => {
    // **The one this file exists for.** A count of 0 here would be a false statement:
    // there may be a dozen cards with no eligible runner and the page simply could not
    // find out.
    const wrapper = render(
      section({
        items: [],
        count: 0,
        unavailable: "節點連線資訊暫時不可用，這一段現在無法回答。",
      }),
    );
    expect(wrapper.get("[data-unavailable]").text()).toContain("暫時不可用");
    expect(wrapper.find("[data-empty]").exists()).toBe(false);
    // And **no count at all**, because a number beside "we could not look" reads as the
    // answer.
    expect(wrapper.find("[data-count]").exists()).toBe(false);
  });

  it("links a card into the board with the drawer already open", () => {
    // The whole point of the page is to get somebody to the card. `?task=` is the Drawer's
    // state, so this lands on the board with the card open rather than on a detail page
    // with no board behind it.
    const href = render(section()).get("[data-card='TK-1']").attributes("href");
    expect(href).toBe("/projects/p-1/work?task=t-1");
  });
});

describe("the six section specs", () => {
  const specs = sectionsFor("u-1");

  it("is six sections in the documented order", () => {
    expect(specs.map((spec) => spec.key)).toEqual([
      "waiting",
      "approval",
      "failed",
      "assigned",
      "no-runner",
      "delivered",
    ]);
  });

  it("marks exactly one section as needing the node registry", () => {
    // Levels 5 and 6 are the two that are not in the database (D92). Only the fifth
    // section filters on one, so only it can be unanswerable.
    expect(
      specs.filter((spec) => spec.needsRuntime).map((spec) => spec.key),
    ).toEqual(["no-runner"]);
  });

  it("gates the approval section on the action rather than hiding it silently", () => {
    expect(specs.find((spec) => spec.key === "approval")?.requires).toBe(
      "task.approve",
    );
  });

  it("says ownership in the first section's caption, because that is the predicate", () => {
    // `task_questions` has no `addressed_to_user_id`, so "a question aimed at me" is not
    // a question this system can be asked (plan/26/08 §3). The caption is deliberately
    // narrower than the ideal rather than promising something the filter cannot do.
    const waiting = specs[0];
    expect(waiting.caption).toContain("你負責的");
    expect(JSON.stringify(waiting.filter)).toContain("owner");
  });

  it("scopes every personal section to the caller", () => {
    const personal = specs.filter((spec) =>
      ["waiting", "failed", "assigned", "no-runner"].includes(spec.key),
    );
    for (const spec of personal) {
      expect(JSON.stringify(spec.filter)).toContain("u-1");
    }
  });

  it("asks for the last seven days of deliveries, not all of them", () => {
    const delivered = specs.find((spec) => spec.key === "delivered")!;
    expect(JSON.stringify(delivered.filter)).toContain("done");
    expect(JSON.stringify(delivered.filter)).toContain("gt");
  });

  it("computes the seven-day boundary from a passed clock", () => {
    // Passed rather than read, so the test is deterministic.
    expect(sevenDaysAgo(Date.parse("2026-08-23T00:00:00Z"))).toBe(
      "2026-08-16T00:00:00.000Z",
    );
  });
});

describe("encodeFilter", () => {
  it("is base64url without padding, which is what the server decodes", () => {
    const encoded = encodeFilter({ field: "risk", op: "eq", value: "high" });
    expect(encoded).not.toContain("=");
    expect(encoded).not.toContain("+");
    expect(encoded).not.toContain("/");
    const padded = encoded + "=".repeat((4 - (encoded.length % 4)) % 4);
    const json = atob(padded.replaceAll("-", "+").replaceAll("_", "/"));
    expect(JSON.parse(json)).toEqual({
      field: "risk",
      op: "eq",
      value: "high",
    });
  });

  it("survives a filter containing non-ASCII, because titles and labels do", () => {
    const encoded = encodeFilter({ field: "risk", op: "eq", value: "高風險" });
    const padded = encoded + "=".repeat((4 - (encoded.length % 4)) % 4);
    const bytes = Uint8Array.from(
      atob(padded.replaceAll("-", "+").replaceAll("_", "/")),
      (character) => character.charCodeAt(0),
    );
    expect(JSON.parse(new TextDecoder().decode(bytes)).value).toBe("高風險");
  });
});
