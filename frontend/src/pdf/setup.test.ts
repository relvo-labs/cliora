// The one place PDF.js is configured (plan/31/05 BP-07 §2, ADR 0029 §12).
//
// `setup_options_are_locked`: getDocument receives exactly the locked option
// set, bytes rather than a URL, and a worker this module created — and no
// caller can change any of it.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getDocument, workers, pdfWorkers } = vi.hoisted(() => ({
  getDocument: vi.fn(),
  workers: [] as Array<{
    url: string;
    options: unknown;
    terminate: ReturnType<typeof vi.fn>;
  }>,
  pdfWorkers: [] as Array<{ port: unknown; destroy: ReturnType<typeof vi.fn> }>,
}));

vi.mock("pdfjs-dist", () => {
  class PDFWorker {
    port: unknown;
    destroy = vi.fn();
    constructor(options: { port: unknown }) {
      this.port = options.port;
      pdfWorkers.push(this);
    }
    static create(options: { port: unknown }) {
      return new PDFWorker(options);
    }
  }
  return {
    getDocument,
    PDFWorker,
    AnnotationMode: {
      DISABLE: 0,
      ENABLE: 1,
      ENABLE_FORMS: 2,
      ENABLE_STORAGE: 3,
    },
  };
});
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({
  default: "/assets/pdf.worker.min-test.mjs",
}));

import {
  LOCKED_OPTIONS,
  PDF_MAX_PAGES,
  openPdf,
  pdfSupported,
  renderPage,
} from "./setup";

class FakeWorker {
  terminate = vi.fn();
  constructor(url: string, options: unknown) {
    workers.push({ url, options, terminate: this.terminate });
  }
}

function fakeTask() {
  return {
    promise: new Promise(() => {}),
    destroy: vi.fn(async () => {}),
    onPassword: null as
      | null
      | ((update: (p: string) => void, reason: number) => void),
  };
}

beforeEach(() => {
  getDocument.mockReset();
  getDocument.mockImplementation(() => fakeTask());
  workers.length = 0;
  pdfWorkers.length = 0;
  vi.stubGlobal("Worker", FakeWorker);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const EXPECTED = {
  isEvalSupported: false,
  enableScripting: false,
  enableXfa: false,
  disableAutoFetch: true,
  disableStream: true,
  disableRange: true,
  stopAtErrors: true,
  cMapUrl: "/pdfjs/cmaps/",
  cMapPacked: true,
  standardFontDataUrl: "/pdfjs/standard_fonts/",
  wasmUrl: "/pdfjs/wasm/",
  iccUrl: "/pdfjs/iccs/",
};

describe("pdf/setup", () => {
  it("setup_options_are_locked", () => {
    const bytes = new Uint8Array([37, 80, 68, 70]);
    openPdf(bytes, { onPassword: () => {} });

    expect(getDocument).toHaveBeenCalledTimes(1);
    const params = getDocument.mock.calls[0][0] as Record<string, unknown>;
    // Exactly the locked set plus the bytes and our own worker: no `url`, so
    // no range or stream request can ever leave the page.
    expect(Object.keys(params).sort()).toEqual(
      [...Object.keys(EXPECTED), "data", "worker"].sort(),
    );
    const { data, worker, ...rest } = params;
    expect(rest).toEqual(EXPECTED);
    expect(data).toBe(bytes);
    expect(worker).toBe(pdfWorkers[0]);
    expect(LOCKED_OPTIONS).toEqual(EXPECTED);
    expect(Object.isFrozen(LOCKED_OPTIONS)).toBe(true);
    expect(PDF_MAX_PAGES).toBe(200);
  });

  it("no caller can override an option", () => {
    const smuggled = {
      onPassword: () => {},
      isEvalSupported: true,
      enableScripting: true,
      url: "https://bp07.example.invalid/x.pdf",
    };
    openPdf(new Uint8Array(4), smuggled as never);
    const params = getDocument.mock.calls[0][0] as Record<string, unknown>;
    expect(params.isEvalSupported).toBe(false);
    expect(params.enableScripting).toBe(false);
    expect(params).not.toHaveProperty("url");
    expect(() => {
      (LOCKED_OPTIONS as Record<string, unknown>).enableXfa = true;
    }).toThrow();
  });

  it("the worker is a same-origin module worker this module owns, handed over as a port", () => {
    openPdf(new Uint8Array(4), { onPassword: () => {} });
    expect(workers).toHaveLength(1);
    expect(workers[0].url).toBe("/assets/pdf.worker.min-test.mjs");
    expect(workers[0].options).toEqual({ type: "module" });
    // A port, so PDF.js never falls back to a main-thread "fake worker".
    expect(pdfWorkers[0].port).toBeInstanceOf(FakeWorker);
  });

  it("a password request is refused: the prompt callback is never answered and the load is destroyed", () => {
    const onPassword = vi.fn();
    const handle = openPdf(new Uint8Array(4), { onPassword });
    const task = getDocument.mock.results[0].value as ReturnType<
      typeof fakeTask
    >;
    expect(typeof task.onPassword).toBe("function");
    const update = vi.fn();
    task.onPassword!(update, 1);
    expect(update).not.toHaveBeenCalled();
    expect(onPassword).toHaveBeenCalledTimes(1);
    expect(task.destroy).toHaveBeenCalledTimes(1);
    expect(handle.destroyed()).toBe(true);
  });

  it("destroy tears down the task, the PDF.js worker and the Worker itself, once", async () => {
    const handle = openPdf(new Uint8Array(4), { onPassword: () => {} });
    const task = getDocument.mock.results[0].value as ReturnType<
      typeof fakeTask
    >;
    await handle.destroy();
    await handle.destroy();
    expect(task.destroy).toHaveBeenCalledTimes(1);
    expect(pdfWorkers[0].destroy).toHaveBeenCalledTimes(1);
    expect(workers[0].terminate).toHaveBeenCalledTimes(1);
  });

  it("the worker is terminated even if PDF.js never finishes its own teardown", async () => {
    vi.useFakeTimers();
    getDocument.mockImplementation(() => ({
      ...fakeTask(),
      destroy: vi.fn(() => new Promise(() => {})),
    }));
    const handle = openPdf(new Uint8Array(4), { onPassword: () => {} });
    const done = handle.destroy();
    expect(workers[0].terminate).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    await done;
    expect(workers[0].terminate).toHaveBeenCalledTimes(1);
  });

  it("renderPage paints appearance streams only: no annotation, text or form layer", () => {
    const render = vi.fn(() => ({
      promise: Promise.resolve(),
      cancel: vi.fn(),
    }));
    const canvas = {} as HTMLCanvasElement;
    const viewport = { width: 1, height: 1 };
    renderPage({ render } as never, canvas, viewport as never);
    expect(render).toHaveBeenCalledWith({
      canvas,
      viewport,
      annotationMode: 1,
    });
  });

  it("pdfSupported needs every builtin the pinned build calls unguarded", () => {
    const builtins: Array<[object, string]> = [
      [Map.prototype, "getOrInsertComputed"],
      [Math, "sumPrecise"],
      [Promise, "try"],
      [Uint8Array, "fromBase64"],
    ];
    const added: Array<[object, string]> = [];
    for (const [owner, name] of builtins) {
      if (!(name in owner)) {
        Object.defineProperty(owner, name, {
          value: () => {},
          configurable: true,
        });
        added.push([owner, name]);
      }
    }
    try {
      expect(pdfSupported()).toBe(true);
      const [owner, name] = builtins[1];
      const saved = Object.getOwnPropertyDescriptor(owner, name)!;
      Reflect.deleteProperty(owner, name);
      expect(pdfSupported()).toBe(false);
      Object.defineProperty(owner, name, saved);
    } finally {
      for (const [owner, name] of added) Reflect.deleteProperty(owner, name);
    }
  });
});
