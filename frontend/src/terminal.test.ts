import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import StatusBadge from "./components/common/StatusBadge.vue";

// Kept from P0 and widened in plan/28. The original assertion was that the
// badge renders its status as text rather than colour alone, which still holds;
// what changed is that the badge no longer prints the raw API value. It used to
// render `reconnecting` — the wire value, in English, lower-cased — because one
// label table served three different vocabularies. Now the caller says which
// vocabulary it is speaking and each has its own words.
describe("terminal presentation", () => {
  it("expresses status with text, not colour alone", () => {
    const wrapper = mount(StatusBadge, {
      props: { status: "reconnecting", kind: "connection", live: true },
    });
    const badge = wrapper.get("[role=status]");
    expect(badge.text()).toContain("重新連線中");
    expect(badge.attributes("data-tone")).toBe("warning");
  });

  it("marks a warning with more than a hue", () => {
    // One of the five themes has a brand colour adjacent to warning, and in
    // none of them is colour allowed to carry the semantic by itself.
    const wrapper = mount(StatusBadge, {
      props: { status: "reconnecting", kind: "connection" },
    });
    expect(wrapper.get(".mark").text()).toBe("!");
  });

  it("does not announce a static label as a live region", () => {
    // A table of twenty rows would otherwise announce twenty things nobody
    // asked about. `live` is for a value that changes while the user watches.
    const wrapper = mount(StatusBadge, {
      props: { status: "online", kind: "node" },
    });
    expect(wrapper.find("[role=status]").exists()).toBe(false);
    expect(wrapper.text()).toContain("線上");
  });

  it("keeps the three vocabularies apart", () => {
    // `exited` means different things to a session and to a browser socket, and
    // the two used to share a CSS rule by coincidence. A session has ended; a
    // socket has lost the process it was watching. Reconnect helps with one of
    // those and does nothing for the other, so the labels must differ.
    const session = mount(StatusBadge, {
      props: { status: "exited", kind: "session" },
    });
    const connection = mount(StatusBadge, {
      props: { status: "exited", kind: "connection" },
    });
    expect(session.text()).toContain("已結束");
    expect(connection.text()).toContain("程序已結束");
    expect(session.text()).not.toBe(connection.text());
  });

  it("shows an unmapped status rather than an empty pill", () => {
    const wrapper = mount(StatusBadge, {
      props: { status: "quiesced", kind: "node" },
    });
    expect(wrapper.text()).toContain("quiesced");
    expect(wrapper.attributes("data-tone")).toBe("neutral");
  });
});
