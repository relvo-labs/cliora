// The PDF page viewer (plan/31/05 BP-07 §3).
//
// PDF.js is faked at `pdf/setup`: each render is a task this test settles by
// hand, so the cases can assert what the viewer does while a page is still
// drawing — which is where the canvas cap, the cancel-on-leave and the per-page
// timeout matter.

import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

interface FakeTask {
  page: number;
  promise: Promise<void>;
  resolve: () => void;
  cancel: ReturnType<typeof vi.fn>;
}
const { tasks } = vi.hoisted(() => ({ tasks: [] as FakeTask[] }));
vi.mock("../../pdf/setup", () => ({
  PDF_PAGE_TIMEOUT_MS: 10_000,
  renderPage: (page: { number: number }) => {
    let resolve!: () => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<void>((a, b) => {
      resolve = a;
      reject = b;
    });
    promise.catch(() => {});
    const task: FakeTask = {
      page: page.number,
      promise,
      resolve,
      cancel: vi.fn(() =>
        reject(
          Object.assign(new Error("cancelled"), {
            name: "RenderingCancelledException",
          }),
        ),
      ),
    };
    tasks.push(task);
    return task;
  },
}));

import PdfPreview from "./PdfPreview.vue";

function fakeDoc(numPages: number) {
  return {
    numPages,
    getPage: vi.fn(async (number: number) => ({
      number,
      getViewport: ({ scale }: { scale: number }) => ({
        width: 612 * scale,
        height: 792 * scale,
        scale,
      }),
      cleanup: vi.fn(),
    })),
  };
}

let wrapper: VueWrapper | undefined;
const registered = new Set<HTMLCanvasElement>();
const tracked = new Set<unknown>();

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await flushPromises();
    await nextTick();
  }
}

async function render(numPages = 40) {
  const doc = fakeDoc(numPages);
  wrapper = mount(PdfPreview, {
    props: {
      doc: doc as never,
      name: "spec.pdf",
      register: (canvas: HTMLCanvasElement) => {
        registered.add(canvas);
        return () => registered.delete(canvas);
      },
      trackRender: (task: unknown) => {
        tracked.add(task);
        return () => tracked.delete(task);
      },
    },
    attachTo: document.body,
  });
  await settle();
  return { doc, w: wrapper };
}

beforeEach(() => {
  tasks.length = 0;
  registered.clear();
  tracked.clear();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => ({}) as never,
  );
});
afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("PdfPreview", () => {
  it("draws page 1 first, labelled for a screen reader, and announces it", async () => {
    const { doc, w } = await render();
    expect(doc.getPage).toHaveBeenCalledWith(1);
    expect(tasks.map((t) => t.page)).toEqual([1]);
    tasks[0].resolve();
    await settle();
    const canvas = w.get("canvas");
    // The backing store is sized to the page (jsdom has no layout, so the
    // fit is 1 and the device pixel ratio 1): 612x792 points, not 300x150.
    const el = canvas.element as HTMLCanvasElement;
    expect([el.width, el.height]).toEqual([612, 792]);
    expect(canvas.attributes("role")).toBe("img");
    expect(canvas.attributes("aria-label")).toBe("第 1／40 頁");
    expect(w.get('[aria-live="polite"]').text()).toContain("第 1／40 頁");
    // The accessibility cost of having no text layer is said on screen (OD-3).
    expect(w.text()).toContain("螢幕報讀器");
  });

  it("paging cancels the page it leaves and never holds more than 3 canvases", async () => {
    const { w } = await render();
    const next = w.get('button[aria-label="下一頁"]');
    for (let i = 0; i < 6; i += 1) {
      await next.trigger("click");
      await settle();
      expect(w.findAll("canvas").length).toBeLessThanOrEqual(3);
      expect(registered.size).toBeLessThanOrEqual(3);
    }
    // Every page left while still drawing had its render cancelled.
    const left = tasks.slice(0, -1);
    expect(left.length).toBeGreaterThan(0);
    for (const task of left) expect(task.cancel).toHaveBeenCalled();
    expect(tasks.at(-1)!.page).toBe(7);
    expect(w.get('[aria-live="polite"]').text()).toContain("第 7／40 頁");
  });

  it("a page that takes longer than 10 s fails on its own; the next page still draws", async () => {
    // Timers only: flushPromises needs setImmediate to stay real.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { w } = await render();
    await vi.advanceTimersByTimeAsync(10_000);
    await settle();
    expect(tasks[0].cancel).toHaveBeenCalled();
    expect(w.text()).toContain("第 1 頁無法在時限內顯示");
    await w.get('button[aria-label="下一頁"]').trigger("click");
    await settle();
    tasks.at(-1)!.resolve();
    await settle();
    expect(w.text()).not.toContain("無法在時限內顯示");
    expect(w.get("canvas").attributes("aria-label")).toBe("第 2／40 頁");
  });

  it("jumps to a typed page number and keeps it within the document", async () => {
    const { doc, w } = await render();
    const input = w.get('input[aria-label="頁碼"]');
    expect(input.attributes("inputmode")).toBe("numeric");
    await input.setValue("17");
    await input.trigger("keydown", { key: "Enter" });
    await settle();
    expect(doc.getPage).toHaveBeenLastCalledWith(17);
    await input.setValue("999");
    await input.trigger("keydown", { key: "Enter" });
    await settle();
    expect(doc.getPage).toHaveBeenLastCalledWith(40);
    expect((input.element as HTMLInputElement).value).toBe("40");
  });

  it("previous is unavailable on page 1 and next on the last page", async () => {
    const { w } = await render(2);
    expect(
      w.get('button[aria-label="上一頁"]').attributes("disabled"),
    ).toBeDefined();
    await w.get('button[aria-label="下一頁"]').trigger("click");
    await settle();
    expect(
      w.get('button[aria-label="下一頁"]').attributes("disabled"),
    ).toBeDefined();
  });

  it("offers nothing active: no password field, no link, no text or annotation layer", async () => {
    const { w } = await render();
    tasks[0].resolve();
    await settle();
    expect(w.find('input[type="password"]').exists()).toBe(false);
    expect(w.find("a").exists()).toBe(false);
    expect(w.find(".textLayer, .annotationLayer").exists()).toBe(false);
  });

  it("unmounting cancels what is drawing and releases every canvas", async () => {
    const { w } = await render();
    w.unmount();
    wrapper = undefined;
    expect(tasks[0].cancel).toHaveBeenCalled();
    expect(registered.size).toBe(0);
    expect(tracked.size).toBe(0);
  });
});
