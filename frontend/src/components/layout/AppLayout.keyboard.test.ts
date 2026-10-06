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
type FrameCallback = (timestamp: number) => void;
let frames: Map<number, FrameCallback>;
let nextFrame: number;
function flushFrame() {
  for (const [id, callback] of frames) {
    frames.delete(id);
    callback(0);
  }
}
function usableHeight() {
  return document.documentElement.style.getPropertyValue(
    "--viewport-usable-height",
  );
}
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
  frames = new Map();
  nextFrame = 0;
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((callback: FrameCallback) => {
      frames.set(++nextFrame, callback);
      return nextFrame;
    }),
  );
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((id: number) => frames.delete(id)),
  );
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

describe("one viewport reading for keyboard chrome and shell height (#130 repair 1)", () => {
  it("synchronizes height changed without an event before focusin", async () => {
    await render();
    viewport.height = 360;
    focus();
    await flushPromises();
    expect(collapsed()).toBe(true);
    expect(usableHeight()).toBe("360px");
  });

  it("reads visualViewport.height only once per sync", async () => {
    await render();
    focus();
    const height = vi.fn().mockReturnValueOnce(360).mockReturnValue(664);
    Object.defineProperty(viewport, "height", { get: height });
    viewport.dispatchEvent(new Event("resize"));
    await flushPromises();
    expect(collapsed()).toBe(true);
    expect(usableHeight()).toBe("360px");
    expect(height).toHaveBeenCalledOnce();
  });

  it("re-reads once on the next frame when height changes after focusin", async () => {
    await render();
    focus();
    expect(usableHeight()).toBe("664px");
    viewport.height = 360;
    flushFrame();
    await flushPromises();
    expect(collapsed()).toBe(true);
    expect(usableHeight()).toBe("360px");
    expect(frames.size).toBe(0);
  });

  it("cancels the pending focus frame on unmount", async () => {
    await render();
    focus();
    expect(frames.size).toBe(1);
    const id = [...frames.keys()][0];
    wrapper.unmount();
    expect(cancelAnimationFrame).toHaveBeenCalledWith(id);
    viewport.height = 360;
    flushFrame();
    expect(usableHeight()).toBe("");
  });

  it("rejects a large clientHeight deficit without an observed viewport drop", async () => {
    vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(
      1200,
    );
    await render();
    focus();
    await flushPromises();
    expect(collapsed()).toBe(false);
    expect(usableHeight()).toBe("664px");
    viewport.change(360);
    await flushPromises();
    expect(collapsed()).toBe(true);
    viewport.change(664);
    await flushPromises();
    expect(collapsed()).toBe(false);
  });

  it("forgets the observed maximum when layout width changes", async () => {
    vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(
      900,
    );
    viewport.height = 900;
    await render(430);
    focus();
    vi.stubGlobal("innerWidth", 390);
    viewport.height = 664;
    window.dispatchEvent(new Event("resize"));
    await flushPromises();
    expect(collapsed()).toBe(false);
    expect(usableHeight()).toBe("664px");
    viewport.change(360);
    await flushPromises();
    expect(collapsed()).toBe(true);
  });

  it("synchronizes a fresh height on a breakpoint change without a viewport event", async () => {
    const narrow = Object.assign(new EventTarget(), { matches: true });
    vi.stubGlobal("matchMedia", (query: string) =>
      query === "(max-width: 767px)"
        ? narrow
        : Object.assign(new EventTarget(), { matches: false }),
    );
    await render();
    focus();
    viewport.change(360);
    await flushPromises();
    expect(collapsed()).toBe(true);
    viewport.height = 664;
    vi.stubGlobal("innerWidth", 768);
    narrow.matches = false;
    narrow.dispatchEvent(
      Object.assign(new Event("change"), { matches: false }),
    );
    await flushPromises();
    expect(collapsed()).toBe(false);
    expect(usableHeight()).toBe("664px");
  });

  it("synchronizes both values on window resize without a viewport event", async () => {
    await render();
    focus();
    viewport.height = 360;
    window.dispatchEvent(new Event("resize"));
    await flushPromises();
    expect(collapsed()).toBe(true);
    expect(usableHeight()).toBe("360px");
  });
});
