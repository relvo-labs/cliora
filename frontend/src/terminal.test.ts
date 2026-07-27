import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import StatusBadge from "./components/common/StatusBadge.vue";

describe("terminal presentation", () => {
  it("expresses status with text, not colour alone", () => {
    const wrapper = mount(StatusBadge, { props: { status: "reconnecting" } });
    const badge = wrapper.get("[role=status]");
    expect(badge.text()).toContain("reconnecting");
    expect(badge.attributes("data-status")).toBe("reconnecting");
  });
});
