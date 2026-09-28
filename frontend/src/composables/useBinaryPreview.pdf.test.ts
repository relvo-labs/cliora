// The PDF half of the preview owner (plan/31/05 BP-07 §3, §4; BP-06 §3).
//
// PDF.js itself is replaced by a fake `pdf/setup`: what is asserted here is the
// owner's side of the contract — when the document is destroyed, what is
// refused before any page renders, and that a password request ends the load.
// setup.test.ts pins what `openPdf` does with PDF.js.

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref, type EffectScope } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import type { User } from "../api/dto";
import { installAuthLossHandler } from "../router/authLoss";
import * as auth from "../stores/auth";
import { previewResponse } from "../testing/binaryPreviewResponse";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (v: T) => void;
  reject: (e: unknown) => void;
};
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  promise.catch(() => {});
  return { promise, resolve, reject };
}

interface FakeDoc {
  numPages: number;
  getPage: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
}
interface FakeHandle {
  task: { promise: Promise<FakeDoc> };
  load: Deferred<FakeDoc>;
  destroy: ReturnType<typeof vi.fn>;
  onPassword: () => void;
}

const { handles, supported } = vi.hoisted(() => ({
  handles: [] as FakeHandle[],
  supported: { value: true },
}));
vi.mock("../pdf/setup", () => ({
  PDF_MAX_PAGES: 200,
  pdfSupported: () => supported.value,
  openPdf: (_bytes: Uint8Array, options: { onPassword: () => void }) => {
    const load = deferred<FakeDoc>();
    const handle: FakeHandle = {
      task: { promise: load.promise },
      load,
      destroy: vi.fn(async () => {}),
      onPassword: options.onPassword,
    };
    handles.push(handle);
    return handle;
  },
}));

import {
  binaryPreviewInflightCount,
  routeHint,
  useBinaryPreview,
} from "./useBinaryPreview";

const A = "44444444-4444-4444-8444-444444444444";
const B = "55555555-5555-4555-8555-555555555555";

function doc(numPages: number): FakeDoc {
  return { numPages, getPage: vi.fn(), destroy: vi.fn(async () => {}) };
}

let fetches = 0;
function stubApi(): void {
  vi.spyOn(auth, "api").mockReturnValue({
    fetchBinaryPreview: vi.fn(async () => {
      fetches += 1;
      return previewResponse({
        meta: { kind: "pdf", mime: "application/pdf", size: 5 },
        bytes: new Uint8Array([37, 80, 68, 70, 45]),
      });
    }),
  } as never);
}

let scope: EffectScope | undefined;
function setup() {
  const sessionId = ref<string | null>(A);
  const enabled = ref(true);
  scope = effectScope();
  const preview = scope.run(() => useBinaryPreview({ sessionId, enabled }))!;
  return { preview, sessionId, enabled };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await nextTick();
  }
  await new Promise((r) => setTimeout(r, 0));
}

async function readyPdf(preview: ReturnType<typeof useBinaryPreview>) {
  void preview.open("docs/spec.pdf");
  await settle();
  expect(handles).toHaveLength(1);
  const document = doc(40);
  handles[0].load.resolve(document);
  await settle();
  expect(preview.state.value).toBe("ready");
  const canvas = globalThis.document.createElement("canvas");
  canvas.width = 600;
  canvas.height = 800;
  preview.registerCanvas(canvas);
  const render = { cancel: vi.fn() };
  preview.trackRender(render);
  return { handle: handles[0], document, canvas, render };
}

function user(id: string): User {
  return {
    id,
    username: id,
    display_name: id,
    role: "Viewer",
    permissions: [],
  };
}
async function signedInWithHandler(): Promise<() => void> {
  const store = auth.useAuthStore();
  store.setTokens({
    access_token: "u1-access",
    refresh_token: "u1-refresh",
    token_type: "bearer",
  });
  store.user = user("u1");
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/login", name: "login", component: { template: "<div/>" } },
      {
        path: "/dashboard",
        name: "dashboard",
        component: { template: "<div/>" },
      },
      { path: "/s", component: { template: "<div/>" } },
    ],
  });
  await router.push("/s");
  return installAuthLossHandler(router);
}

let stopHandler: (() => void) | undefined;
beforeEach(() => {
  setActivePinia(createPinia());
  handles.length = 0;
  supported.value = true;
  fetches = 0;
  stubApi();
});
afterEach(async () => {
  await settle();
  scope?.stop();
  scope = undefined;
  stopHandler?.();
  stopHandler = undefined;
  vi.restoreAllMocks();
});

describe("useBinaryPreview — PDF", () => {
  it("routes .pdf through the binary path", () => {
    expect(routeHint("docs/Spec.PDF")).toBe(true);
    expect(routeHint("docs/notes.pdf.txt")).toBe(false);
  });

  it("page_limit_before_render: 10 000 pages is refused before a page is asked for", async () => {
    const { preview } = setup();
    void preview.open("huge.pdf");
    await settle();
    const document = doc(10_000);
    handles[0].load.resolve(document);
    await settle();
    expect(preview.state.value).toBe("pdf_too_many_pages");
    expect(preview.detail.value).toMatchObject({ pages: 10_000, limit: 200 });
    expect(document.getPage).not.toHaveBeenCalled();
    expect(preview.pdf.value).toBeNull();
    expect(handles[0].destroy).toHaveBeenCalled();
  });

  it("exactly the limit is allowed", async () => {
    const { preview } = setup();
    void preview.open("ok.pdf");
    await settle();
    handles[0].load.resolve(doc(200));
    await settle();
    expect(preview.state.value).toBe("ready");
  });

  it("a password request ends the load: pdf_password_required, and the document is destroyed", async () => {
    const { preview } = setup();
    void preview.open("secret.pdf");
    await settle();
    handles[0].onPassword();
    const error = Object.assign(new Error("No password given"), {
      name: "PasswordException",
    });
    handles[0].load.reject(error);
    await settle();
    expect(preview.state.value).toBe("pdf_password_required");
    expect(handles[0].destroy).toHaveBeenCalled();
    expect(preview.pdf.value).toBeNull();
  });

  it("a document PDF.js cannot open is render_failed", async () => {
    const { preview } = setup();
    void preview.open("broken.pdf");
    await settle();
    handles[0].load.reject(
      Object.assign(new Error("Invalid PDF"), { name: "InvalidPDFException" }),
    );
    await settle();
    expect(preview.state.value).toBe("render_failed");
    expect(handles[0].destroy).toHaveBeenCalled();
  });

  it("no usable PDF.js in this browser: unsupported_browser, nothing fetched", async () => {
    supported.value = false;
    const { preview } = setup();
    await preview.open("ok.pdf");
    await settle();
    expect(preview.state.value).toBe("unsupported_browser");
    expect(fetches).toBe(0);
    expect(handles).toHaveLength(0);
  });

  it("a document that finishes loading after a session switch is destroyed, never shown", async () => {
    const { preview, sessionId } = setup();
    void preview.open("docs/spec.pdf");
    await settle();
    sessionId.value = B;
    const document = doc(3);
    handles[0].load.resolve(document);
    await settle();
    expect(preview.pdf.value).toBeNull();
    expect(preview.state.value).toBe("idle");
    expect(handles[0].destroy).toHaveBeenCalled();
    expect(binaryPreviewInflightCount()).toBe(0);
  });
});

describe("useBinaryPreview — destroy_on_every_trigger", () => {
  const triggers: Array<[string, (ctx: ReturnType<typeof setup>) => void]> = [
    ["close", ({ preview }) => preview.close()],
    ["path change", ({ preview }) => void preview.open("other.pdf")],
    ["unmount", () => scope?.stop()],
    ["session id change", ({ sessionId }) => void (sessionId.value = B)],
    ["capability drop", ({ enabled }) => void (enabled.value = false)],
  ];
  for (const [name, trigger] of triggers) {
    it(name, async () => {
      const ctx = setup();
      const { handle, canvas, render } = await readyPdf(ctx.preview);
      trigger(ctx);
      // In the same call: renders cancelled, document and worker torn down,
      // canvases zeroed (ADR 0029 §14 order).
      expect(render.cancel).toHaveBeenCalledTimes(1);
      expect(handle.destroy).toHaveBeenCalledTimes(1);
      expect(canvas.width).toBe(0);
      expect(canvas.height).toBe(0);
      expect(ctx.preview.pdf.value).toBeNull();
    });
  }

  it("sign-out (through the auth-loss handler)", async () => {
    stopHandler = await signedInWithHandler();
    const ctx = setup();
    const { handle, canvas, render } = await readyPdf(ctx.preview);
    auth.useAuthStore().clearTokens();
    expect(render.cancel).toHaveBeenCalledTimes(1);
    expect(handle.destroy).toHaveBeenCalledTimes(1);
    expect(canvas.width).toBe(0);
  });

  it("user change (through the auth-loss handler)", async () => {
    stopHandler = await signedInWithHandler();
    const ctx = setup();
    const { handle } = await readyPdf(ctx.preview);
    auth.useAuthStore().user = user("u2");
    expect(handle.destroy).toHaveBeenCalledTimes(1);
  });

  it("identity pending keeps the document (it may be the same user)", async () => {
    stopHandler = await signedInWithHandler();
    const ctx = setup();
    const { handle, canvas } = await readyPdf(ctx.preview);
    auth.useAuthStore().identityPending = true;
    expect(handle.destroy).not.toHaveBeenCalled();
    expect(canvas.width).toBe(600);
    expect(ctx.preview.state.value).toBe("ready");
  });

  it("a render task finished before disposal is not cancelled twice", async () => {
    const ctx = setup();
    const { render } = await readyPdf(ctx.preview);
    const untrack = ctx.preview.trackRender({ cancel: vi.fn() });
    untrack();
    ctx.preview.close();
    expect(render.cancel).toHaveBeenCalledTimes(1);
  });
});
