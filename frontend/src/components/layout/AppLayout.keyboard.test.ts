import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createMemoryHistory } from "vue-router";

import AppLayout from "./AppLayout.vue";

// Inject the browser viewport, not a production-only keyboard override.
class Viewport extends EventTarget {
  height = 664;
  scale = 1;
  change(height: number, event = "resize") {
    this.height = height;
    this.dispatchEvent(new Event(event));
  }
}
let viewport: Viewport;
let wrapper: ReturnType<typeof mount>;
async function render(width = 390, optIn = true) {
  vi.stubGlobal("innerWidth", width);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/", component: { template: "<div/>" } }],
  });
  await router.push("/");
  wrapper = mount(AppLayout, {
    props: { fill: true, collapseOnKeyboard: optIn },
    slots: {
      default: '<textarea aria-label="terminal input"/><button>other</button>',
    },
    global: { plugins: [router], stubs: { PrimaryNav: true } },
    attachTo: document.body,
  });
  return wrapper;
}
function focus() {
  wrapper.get("textarea").element.focus();
}
function collapsed() {
  return wrapper.get(".shell").attributes("data-keyboard-collapsed") === "";
}
beforeEach(() => {
  setActivePinia(createPinia());
  viewport = new Viewport();
  vi.stubGlobal("visualViewport", viewport);
  vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(
    664,
  );
});
afterEach(() => {
  wrapper?.unmount();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("phone keyboard detection (#130)", () => {
  it("collapses at a large deficit with terminal input focused and restores on close", async () => {
    await render();
    focus();
    viewport.change(360);
    await flushPromises();
    expect(collapsed()).toBe(true);
    expect(wrapper.get("header").isVisible()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get("textarea").element);
    viewport.change(664);
    await flushPromises();
    expect(collapsed()).toBe(false);
    expect(wrapper.get("header").isVisible()).toBe(true);
  });

  it("handles viewport scroll before focus arrives (iOS event ordering)", async () => {
    await render();
    viewport.change(360, "scroll");
    await flushPromises();
    expect(collapsed()).toBe(false);
    focus();
    await flushPromises();
    expect(collapsed()).toBe(true);
  });

  it("keeps chrome collapsed after blur until the viewport recovers", async () => {
    await render();
    focus();
    viewport.change(360);
    await flushPromises();
    wrapper.get("textarea").element.blur();
    await flushPromises();
    expect(collapsed()).toBe(true);
    viewport.change(664);
    await flushPromises();
    expect(collapsed()).toBe(false);
  });

  it.each([600, 515])(
    "ignores browser toolbar-sized deficits: %ipx",
    async (height) => {
      await render();
      focus();
      viewport.change(height);
      await flushPromises();
      expect(collapsed()).toBe(false);
    },
  );

  it("also requires at least 25 percent of the layout height", async () => {
    vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(
      1000,
    );
    viewport.height = 1000;
    await render();
    focus();
    viewport.change(800);
    await flushPromises();
    expect(collapsed()).toBe(false);
  });

  it("does not treat pinch zoom as a keyboard", async () => {
    await render();
    focus();
    viewport.scale = 2;
    viewport.change(360);
    await flushPromises();
    expect(collapsed()).toBe(false);
  });

  it("requires editable focus to enter the collapsed state", async () => {
    await render();
    wrapper.get("button").element.focus();
    viewport.change(360);
    await flushPromises();
    expect(collapsed()).toBe(false);
  });

  it.each([768, 1024, 1440])(
    "leaves %ipx tablet/desktop chrome unchanged",
    async (width) => {
      await render(width);
      focus();
      viewport.change(360);
      await flushPromises();
      expect(collapsed()).toBe(false);
      expect(wrapper.get("header").isVisible()).toBe(true);
    },
  );

  it("keeps other pages unchanged", async () => {
    await render(390, false);
    focus();
    viewport.change(360);
    await flushPromises();
    expect(collapsed()).toBe(false);
  });

  it("removes viewport, focus and window listeners on unmount", async () => {
    const vvRemove = vi.spyOn(viewport, "removeEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const windowRemove = vi.spyOn(window, "removeEventListener");
    await render();
    wrapper.unmount();
    expect(vvRemove.mock.calls.map(([type]) => type)).toEqual([
      "resize",
      "scroll",
    ]);
    expect(docRemove.mock.calls.map(([type]) => type)).toContain("focusin");
    expect(windowRemove.mock.calls.map(([type]) => type)).toContain("resize");
    expect(
      document.documentElement.style.getPropertyValue(
        "--viewport-usable-height",
      ),
    ).toBe("");
  });

  it("falls back without visualViewport", async () => {
    vi.stubGlobal("visualViewport", undefined);
    await render();
    focus();
    await flushPromises();
    expect(collapsed()).toBe(false);
  });
});
