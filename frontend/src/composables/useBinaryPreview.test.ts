// The binary preview's single owner (plan/31/05 BP-06 §2, §3, §5).
//
// Fresh Pinia per case and nothing pre-bound: the #76 lesson was that a test
// which binds the store itself cannot see who is supposed to bind it. The auth
// cases install the real auth-loss handler and change the real auth store, so
// "cleared in the same tick" is asserted against the production wiring, not
// against a direct call to `clear()`.

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref, type EffectScope } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { ApiClient, ApiError } from "../api/client";
import type { BinaryPreviewPayload, User } from "../api/dto";
import { installAuthLossHandler } from "../router/authLoss";
import * as auth from "../stores/auth";
import { previewResponse } from "../testing/binaryPreviewResponse";
import {
  binaryPreviewInflightCount,
  useBinaryPreview,
} from "./useBinaryPreview";

const A = "44444444-4444-4444-8444-444444444444";
const B = "55555555-5555-4555-8555-555555555555";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
};
function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function payload(
  over: Partial<BinaryPreviewPayload["meta"]> = {},
): BinaryPreviewPayload {
  return {
    meta: {
      kind: "image",
      mime: "image/png",
      size: 4,
      width: 20,
      height: 10,
      ...over,
    },
    bytes: new Uint8Array([1, 2, 3, 4]),
  };
}

interface FakeBitmap {
  width: number;
  height: number;
  close: ReturnType<typeof vi.fn>;
}
let bitmaps: FakeBitmap[] = [];
const createImageBitmapMock = vi.fn(async () => {
  const bitmap = { width: 20, height: 10, close: vi.fn() };
  bitmaps.push(bitmap);
  return bitmap;
});

// Every call to the API goes through here, with one deferred per request so a
// case decides when (and whether) each response lands.
let pending: Array<{
  sessionId: string;
  path: string;
  signal?: AbortSignal;
  reply: Deferred<BinaryPreviewPayload>;
}> = [];
function stubApi(): void {
  vi.spyOn(auth, "api").mockReturnValue({
    fetchBinaryPreview: vi.fn(
      (
        sessionId: string,
        path: string,
        options: { signal?: AbortSignal } = {},
      ) => {
        const reply = deferred<BinaryPreviewPayload>();
        pending.push({ sessionId, path, signal: options.signal, reply });
        return reply.promise.then(previewResponse);
      },
    ),
  } as never);
}

let scope: EffectScope | undefined;
function setup(initial: { sessionId?: string | null; enabled?: boolean } = {}) {
  const sessionId = ref<string | null>(
    initial.sessionId === undefined ? A : initial.sessionId,
  );
  const enabled = ref(initial.enabled ?? true);
  scope = effectScope();
  const preview = scope.run(() => useBinaryPreview({ sessionId, enabled }))!;
  return { preview, sessionId, enabled };
}

// A canvas the owner has been handed, sized as a painted one would be.
function paintedCanvas(): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = 20;
  canvas.height = 10;
  return canvas;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await Promise.resolve();
    await nextTick();
  }
}

async function ready(preview: ReturnType<typeof useBinaryPreview>) {
  void preview.open("img/a.png");
  pending.at(-1)!.reply.resolve(payload());
  await settle();
  expect(preview.state.value).toBe("ready");
  const canvas = paintedCanvas();
  preview.registerCanvas(canvas);
  return { canvas, bitmap: bitmaps.at(-1)! };
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

function signIn(id: string): void {
  const store = auth.useAuthStore();
  store.setTokens({
    access_token: `${id}-access`,
    refresh_token: `${id}-refresh`,
    token_type: "bearer",
  });
  store.user = user(id);
}

let stopAuthLoss: (() => void) | undefined;
async function installHandler(): Promise<void> {
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
  stopAuthLoss = installAuthLossHandler(router);
}

beforeEach(() => {
  setActivePinia(createPinia());
  bitmaps = [];
  pending = [];
  createImageBitmapMock.mockClear();
  vi.stubGlobal("createImageBitmap", createImageBitmapMock);
  stubApi();
});
afterEach(async () => {
  // The auth-loss handler leaves the page asynchronously; let that settle in
  // this case's own Pinia rather than the next one's.
  await settle();
  await new Promise((r) => setTimeout(r, 0));
  scope?.stop();
  scope = undefined;
  stopAuthLoss?.();
  stopAuthLoss = undefined;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useBinaryPreview — session binding", () => {
  it("session_switch_mid_transfer_never_paints", async () => {
    const { preview, sessionId } = setup();
    void preview.open("img/a.png");
    expect(pending).toHaveLength(1);
    expect(pending[0].sessionId).toBe(A);

    sessionId.value = B;
    // Cleared before anything for B can render (先清再換), and A's request
    // was told to stop.
    expect(preview.state.value).toBe("idle");
    expect(pending[0].signal?.aborted).toBe(true);

    // A late answer for A arrives anyway (a server that ignores the abort).
    pending[0].reply.resolve(payload());
    await settle();

    expect(createImageBitmapMock).not.toHaveBeenCalled();
    expect(preview.bitmap.value).toBeNull();
    expect(preview.state.value).toBe("idle");
    expect(binaryPreviewInflightCount()).toBe(0);
  });

  it("session ended: no request at all", async () => {
    const { preview } = setup({ sessionId: null });
    await preview.open("img/a.png");
    expect(pending).toHaveLength(0);
    expect(preview.state.value).toBe("session_ended");
  });
});

describe("useBinaryPreview — auth loss (the #76 handler, not a direct call)", () => {
  it("auth_loss_clears_in_same_tick", async () => {
    signIn("u1");
    await installHandler();
    const { preview } = setup();
    const { canvas, bitmap } = await ready(preview);

    // Another tab signed out: the storage sync clears this tab's tokens.
    auth.useAuthStore().clearTokens();

    // Same synchronous call: no await, no tick between.
    expect(bitmap.close).toHaveBeenCalledTimes(1);
    expect(canvas.width).toBe(0);
    expect(canvas.height).toBe(0);
    expect(preview.state.value).toBe("idle");
    expect(preview.bitmap.value).toBeNull();
  });

  it("user_switch_clears", async () => {
    signIn("u1");
    await installHandler();
    const { preview } = setup();
    const { canvas, bitmap } = await ready(preview);

    auth.useAuthStore().user = user("u2");

    expect(bitmap.close).toHaveBeenCalledTimes(1);
    expect(canvas.width).toBe(0);
    expect(preview.state.value).toBe("idle");
  });

  // Two cases, because under 先清再換 a load and a painted image never coexist:
  // opening anything disposes what was on screen first.
  it("identity_pending_aborts_only: a transfer in flight is aborted", async () => {
    signIn("u1");
    await installHandler();
    const { preview } = setup();
    void preview.open("img/a.png");
    const inflight = pending.at(-1)!;
    expect(inflight.signal?.aborted).toBe(false);

    auth.useAuthStore().identityPending = true;

    expect(inflight.signal?.aborted).toBe(true);
    expect(binaryPreviewInflightCount()).toBe(0);
    // The late answer is not painted even if it arrives.
    inflight.reply.resolve(payload());
    await settle();
    expect(createImageBitmapMock).not.toHaveBeenCalled();
  });

  it("identity_pending_aborts_only: what is on screen stays (it may be the same user)", async () => {
    signIn("u1");
    await installHandler();
    const { preview } = setup();
    const { canvas, bitmap } = await ready(preview);

    auth.useAuthStore().identityPending = true;

    expect(bitmap.close).not.toHaveBeenCalled();
    expect(canvas.width).toBe(20);
    expect(preview.state.value).toBe("ready");
    expect(preview.bitmap.value).not.toBeNull();
  });
});

describe("useBinaryPreview — what reaches the decoder", () => {
  it("header_limits_rechecked", async () => {
    const { preview } = setup();
    void preview.open("img/huge.png");
    pending[0].reply.resolve(payload({ width: 9000, height: 9000 }));
    await settle();
    expect(createImageBitmapMock).not.toHaveBeenCalled();
    expect(preview.state.value).toBe("limit");
  });

  it("header pixel count over the cap is refused even with both sides in range", async () => {
    const { preview } = setup();
    void preview.open("img/wide.png");
    pending[0].reply.resolve(payload({ width: 8192, height: 4096 }));
    await settle();
    expect(createImageBitmapMock).not.toHaveBeenCalled();
    expect(preview.state.value).toBe("limit");
    expect(preview.detail.value.reason).toBe("pixels");
  });

  it("length_mismatch_is_error", async () => {
    // The real client this time, with a stream that stops short.
    const short = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2]));
        controller.close();
      },
    });
    const fetchImpl = vi.fn(
      async () =>
        new Response(short, {
          status: 200,
          headers: {
            "Content-Length": "10",
            "X-Cliora-Preview-Mime": "image/png",
            "X-Cliora-Preview-Kind": "image",
            "X-Cliora-Preview-Width": "2",
            "X-Cliora-Preview-Height": "1",
          },
        }),
    );
    const real = new ApiClient(
      {
        accessToken: () => "t",
        refreshToken: () => null,
        setTokens: () => {},
        clear: () => {},
      },
      fetchImpl as unknown as typeof fetch,
    );
    vi.spyOn(auth, "api").mockReturnValue(real);
    const { preview } = setup();
    await preview.open("img/a.png");
    await settle();
    expect(preview.state.value).toBe("transfer_failed");
    expect(createImageBitmapMock).not.toHaveBeenCalled();
    expect(preview.bitmap.value).toBeNull();
  });

  it("a decoder failure is render_failed and leaves nothing behind", async () => {
    createImageBitmapMock.mockRejectedValueOnce(new Error("decode"));
    const { preview } = setup();
    void preview.open("img/a.png");
    pending[0].reply.resolve(payload());
    await settle();
    expect(preview.state.value).toBe("render_failed");
    expect(preview.bitmap.value).toBeNull();
  });

  it("no createImageBitmap: unsupported_browser, and nothing is fetched", async () => {
    vi.stubGlobal("createImageBitmap", undefined);
    const { preview } = setup();
    await preview.open("img/a.png");
    expect(pending).toHaveLength(0);
    expect(preview.state.value).toBe("unsupported_browser");
  });

  it("decodes from a Blob with EXIF orientation, never via an object URL", async () => {
    // jsdom has no createObjectURL; install a spy for the length of the case.
    const createObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      value: createObjectURL,
      configurable: true,
      writable: true,
    });
    try {
      const { preview } = setup();
      void preview.open("img/a.png");
      pending[0].reply.resolve(payload());
      await settle();
      expect(createImageBitmapMock).toHaveBeenCalledTimes(1);
      const [source, options] = createImageBitmapMock.mock
        .calls[0] as unknown as [Blob, { imageOrientation?: string }];
      expect(source).toBeInstanceOf(Blob);
      expect(source.type).toBe("image/png");
      expect(options).toEqual({ imageOrientation: "from-image" });
      expect(createObjectURL).not.toHaveBeenCalled();
    } finally {
      Reflect.deleteProperty(URL, "createObjectURL");
    }
  });
});

describe("useBinaryPreview — refusals map to distinct states", () => {
  const cases: Array<[ApiError, string]> = [
    [
      new ApiError("FILE_DENIED", "x", 403, "r", { reason: "dotenv" }),
      "denied_sensitive",
    ],
    [
      new ApiError("FILE_DENIED", "x", 403, "r", { reason: "outside_root" }),
      "denied_access",
    ],
    [new ApiError("FILE_NOT_FOUND", "x", 404, "r"), "denied_access"],
    [new ApiError("FILE_PERMISSION_DENIED", "x", 403, "r"), "permission"],
    [
      new ApiError("FILE_TOO_LARGE", "x", 413, "r", {
        reason: "too_large",
        size: 9,
        limit: 8,
      }),
      "too_large",
    ],
    [
      new ApiError("FILE_PREVIEW_LIMIT", "x", 413, "r", {
        reason: "dimensions",
      }),
      "limit",
    ],
    [
      new ApiError("FILE_PREVIEW_INVALID", "x", 422, "r", {
        reason: "malformed",
      }),
      "invalid",
    ],
    [
      new ApiError("FILE_PREVIEW_INVALID", "x", 422, "r", {
        reason: "changed",
      }),
      "changed",
    ],
    [
      new ApiError("FILE_PREVIEW_UNSUPPORTED", "x", 415, "r", {
        reason: "unsupported_type",
      }),
      "unsupported",
    ],
    [new ApiError("NODE_OFFLINE", "x", 409, "r"), "offline"],
    [new ApiError("FORBIDDEN", "x", 403, "r"), "forbidden"],
    [new ApiError("FILE_PREVIEW_BUSY", "x", 429, "r"), "busy"],
    [new ApiError("NODE_BUSY", "x", 503, "r"), "busy"],
    [new ApiError("FILE_PREVIEW_EXPIRED", "x", 502, "r"), "transfer_failed"],
    [new ApiError("REQUEST_TIMEOUT", "x", 504, "r"), "transfer_failed"],
    [
      new ApiError("FILE_PREVIEW_UNSUPPORTED_NODE", "x", 409, "r"),
      "node_unsupported",
    ],
  ];
  for (const [error, state] of cases) {
    it(`${error.code}${error.details?.reason ? `/${error.details.reason}` : ""} → ${state}`, async () => {
      const { preview } = setup();
      void preview.open("img/a.png");
      pending[0].reply.reject(error);
      await settle();
      expect(preview.state.value).toBe(state);
    });
  }
});

describe("useBinaryPreview — inflight_zero_after_dispose", () => {
  const triggers: Array<
    [string, (ctx: ReturnType<typeof setup>) => void | Promise<void>]
  > = [
    ["close", ({ preview }) => preview.close()],
    ["cancel", ({ preview }) => preview.cancel()],
    ["dispose (unmount)", () => scope?.stop()],
    ["session id change", ({ sessionId }) => void (sessionId.value = B)],
    ["capability drop", ({ enabled }) => void (enabled.value = false)],
    ["path change (open another)", ({ preview }) => void preview.open("b.png")],
  ];
  for (const [name, trigger] of triggers) {
    it(name, async () => {
      const ctx = setup();
      void ctx.preview.open("img/a.png");
      expect(binaryPreviewInflightCount()).toBe(1);
      await trigger(ctx);
      // Opening another file starts exactly one new request; everything else
      // leaves none.
      expect(binaryPreviewInflightCount()).toBe(
        name.startsWith("path change") ? 1 : 0,
      );
      expect(pending[0].signal?.aborted).toBe(true);
    });
  }

  it("sign-out and user switch through the handler", async () => {
    signIn("u1");
    await installHandler();
    const { preview } = setup();
    void preview.open("img/a.png");
    auth.useAuthStore().user = user("u2");
    expect(binaryPreviewInflightCount()).toBe(0);
    void preview.open("img/a.png");
    expect(binaryPreviewInflightCount()).toBe(1);
    auth.useAuthStore().clearTokens();
    expect(binaryPreviewInflightCount()).toBe(0);
  });

  it("capability drop disposes what is on screen too", async () => {
    const { preview, enabled } = setup();
    const { canvas, bitmap } = await ready(preview);
    enabled.value = false;
    expect(bitmap.close).toHaveBeenCalledTimes(1);
    expect(canvas.width).toBe(0);
    expect(preview.state.value).toBe("idle");
  });
});
