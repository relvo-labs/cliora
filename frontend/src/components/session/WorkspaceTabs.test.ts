import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { nextTick } from "vue";

import WorkspaceTabs, { type WorkspaceTab } from "./WorkspaceTabs.vue";

const TABS: WorkspaceTab[] = [
  { id: "cli", label: "CLI" },
  { id: "preview", label: "app.py", title: "src/app.py", closable: true },
];

function render(active = "cli", tabs = TABS) {
  return mount(WorkspaceTabs, {
    props: { tabs, active },
    attachTo: document.body,
  });
}

describe("WorkspaceTabs", () => {
  it("exposes the tablist/tab/tabpanel wiring a screen reader needs", () => {
    const wrapper = render("preview");
    expect(wrapper.get('[role="tablist"]')).toBeTruthy();
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs).toHaveLength(2);
    expect(tabs[0].attributes("aria-selected")).toBe("false");
    expect(tabs[1].attributes("aria-selected")).toBe("true");
    // Each tab names the panel it controls, and the panel names it back
    // (the view sets aria-labelledby="tab-<id>" on the panel).
    expect(tabs[0].attributes("id")).toBe("tab-cli");
    expect(tabs[0].attributes("aria-controls")).toBe("panel-cli");
    expect(tabs[1].attributes("aria-controls")).toBe("panel-preview");
  });

  it("is a single tab stop: only the selected tab is reachable by Tab", () => {
    const tabs = render("cli").findAll('[role="tab"]');
    expect(tabs[0].attributes("tabindex")).toBe("0");
    expect(tabs[1].attributes("tabindex")).toBe("-1");
  });

  it("moves and activates with the arrow keys, wrapping at both ends", async () => {
    const wrapper = render("cli");
    const list = wrapper.get('[role="tablist"]');

    await list.trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.emitted("select")?.at(-1)).toEqual(["preview"]);

    // Wraps back round to the first tab rather than dead-ending.
    await wrapper.setProps({ active: "preview" });
    await list.trigger("keydown", { key: "ArrowRight" });
    expect(wrapper.emitted("select")?.at(-1)).toEqual(["cli"]);
  });

  it("Home and End jump to the ends", async () => {
    const wrapper = render("cli");
    const list = wrapper.get('[role="tablist"]');
    await list.trigger("keydown", { key: "End" });
    expect(wrapper.emitted("select")?.at(-1)).toEqual(["preview"]);

    await wrapper.setProps({ active: "preview" });
    await list.trigger("keydown", { key: "Home" });
    expect(wrapper.emitted("select")?.at(-1)).toEqual(["cli"]);
  });

  it("moves DOM focus with the selection so the keyboard user follows", async () => {
    const wrapper = render("cli");
    await wrapper.get('[role="tablist"]').trigger("keydown", { key: "End" });
    await wrapper.setProps({ active: "preview" });
    await nextTick();
    expect(document.activeElement).toBe(
      wrapper.findAll('[role="tab"]')[1].element,
    );
  });

  it("re-selecting the active tab emits nothing", async () => {
    const wrapper = render("cli");
    await wrapper.findAll('[role="tab"]')[0].trigger("click");
    expect(wrapper.emitted("select")).toBeUndefined();
  });

  it("only a closable tab has a close button, and it names its target", async () => {
    const wrapper = render("preview");
    const closes = wrapper.findAll(".close");
    expect(closes).toHaveLength(1);
    expect(closes[0].attributes("aria-label")).toBe("關閉 app.py");
    await closes[0].trigger("click");
    expect(wrapper.emitted("close")).toEqual([["preview"]]);
  });

  it("shows the full path on hover without putting it in the label", () => {
    const tab = render("preview").findAll('[role="tab"]')[1];
    expect(tab.text()).toBe("app.py");
    expect(tab.attributes("title")).toBe("src/app.py");
  });
});
