// Node posture is visible before the user types, at every width.
//
// ADR 0023 D10 is a security requirement, not a layout preference: a session on
// a node whose sandbox is off, or that can escalate through sudo, has to say so
// while the user can still decide not to type. The header already carried a
// comment saying exactly that — and the posture badges were on the identity
// row, which collapses behind a disclosure from 1024px down. So from 1024px the
// requirement was not met, and the comment asserting it was met sat four lines
// above the `v-if` that broke it (plan/29 MS-06).
//
// These cases are about that one rule. They deliberately do not assert wording:
// compact shortens the labels, and pinning the strings would make a copy edit
// look like a regression.

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import SessionHeader from "./SessionHeader.vue";

function render(props: Record<string, unknown> = {}) {
  return mount(SessionHeader, {
    props: {
      name: "refactor-api",
      runtime: "claude",
      workspace: "/srv/work/api",
      ...props,
    },
    global: {
      stubs: {
        UiActionMenu: { template: "<div><slot :close='() => {}' /></div>" },
      },
    },
  });
}

describe("SessionHeader — 姿態在任何寬度都看得見", () => {
  for (const compact of [false, true]) {
    it(`compact=${compact}：沙箱停用的警示直接可見，不在揭露之後`, () => {
      const wrapper = render({ compact, sandboxBypassed: true });
      const badges = wrapper.findAll(".posture");
      expect(badges).toHaveLength(1);
      expect(badges[0].text().length).toBeGreaterThan(0);
    });

    it(`compact=${compact}：可提權的警示直接可見`, () => {
      const wrapper = render({ compact, privilegedNode: true });
      expect(wrapper.findAll(".posture")).toHaveLength(1);
    });

    it(`compact=${compact}：兩種姿態同時成立時都在`, () => {
      const wrapper = render({
        compact,
        sandboxBypassed: true,
        privilegedNode: true,
      });
      expect(wrapper.findAll(".posture")).toHaveLength(2);
    });
  }

  it("姿態不在會被收起的那一列裡", () => {
    // The structural half. The cases above would still pass if someone moved
    // the badges back onto the identity row and happened to leave the
    // disclosure open by default; this one says where they live.
    const wrapper = render({
      compact: true,
      sandboxBypassed: true,
      privilegedNode: true,
    });
    expect(wrapper.find(".row.identity").exists()).toBe(false);
    expect(wrapper.findAll(".row.primary .posture")).toHaveLength(2);
  });

  it("沒有姿態可報時不渲染任何徽章", () => {
    // A warning that is always present stops being a warning.
    expect(render({ compact: true }).findAll(".posture")).toHaveLength(0);
  });
});
