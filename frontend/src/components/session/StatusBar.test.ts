import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import StatusBar from "./StatusBar.vue";

describe("StatusBar — ended sessions (#107)", () => {
  for (const [sessionStatus, label] of [
    ["exited", "已結束"],
    ["failed", "失敗"],
    ["terminated", "已終止"],
  ]) {
    it(`${sessionStatus} replaces writer control with the end state`, () => {
      const wrapper = mount(StatusBar, {
        props: { sessionStatus, connection: "connected", role: "writer" },
      });
      expect(wrapper.text()).toContain(label);
      expect(wrapper.text()).not.toContain("你有控制權");
      expect(wrapper.find(".plain.accent").exists()).toBe(false);
    });
  }

  it("socket exit wins over a stale running payload", () => {
    const wrapper = mount(StatusBar, {
      props: {
        sessionStatus: "running",
        connection: "exited",
        role: "writer",
      },
    });
    expect(wrapper.text()).toContain("已結束");
    expect(wrapper.text()).not.toContain("執行中");
    expect(wrapper.text()).not.toContain("你有控制權");
  });

  it("a live writer still has control", () => {
    const wrapper = mount(StatusBar, {
      props: {
        sessionStatus: "running",
        connection: "connected",
        role: "writer",
      },
    });
    expect(wrapper.text()).toContain("你有控制權");
  });
});
