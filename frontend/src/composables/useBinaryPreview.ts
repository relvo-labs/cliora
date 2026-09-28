// Read-only binary preview lifecycle (ADR 0029 §11, §14; plan/31/05 BP-06).
//
// The single owner of everything a binary preview holds: the AbortController,
// the bytes, the decoded ImageBitmap and every canvas painted from it. None of
// it is reactive state — the bitmap sits in a `shallowRef` and is `markRaw`,
// the bytes are a local that goes out of scope the moment the decoder has
// them, and the canvases are a plain Set.
//
// Two rules carry the security weight, both inherited from #76:
//   * a response for a session, a file or a user that is no longer the one on
//     screen is dropped, never painted (`stale()` below);
//   * every disposal trigger clears *before* the next state renders — session
//     change, capability loss, sign-out and user change all run in the same
//     synchronous call as the change itself (flush: "sync").
//
// No object URL is created, by design: the image is decoded from a Blob in
// script and drawn to a canvas, which offers no "save image" (ADR 0029 §11).

import { markRaw, onScopeDispose, ref, shallowRef, watch, type Ref } from "vue";

import { ApiError, isAbortError } from "../api/client";
import type {
  BinaryPreviewKind,
  BinaryPreviewMeta,
  BinaryPreviewMime,
  BinaryPreviewPayload,
} from "../api/dto";
import { api, useAuthStore } from "../stores/auth";
import {
  registerBinaryPreviewOwner,
  useBinaryPreviewStore,
} from "../stores/binaryPreview";

// A routing hint only, never an authorisation: the daemon decides what a file
// is from its bytes, and a `.png` that is really text comes back
// `unsupported` (plan/31/05 BP-06 §1).
export const BINARY_PREVIEW_HINT = /\.(png|jpe?g|webp|gif)$/i;
export function routeHint(relPath: string): boolean {
  return BINARY_PREVIEW_HINT.test(relPath);
}

// ADR 0029 §4 (OD-2). The daemon enforces both from the header; the browser
// re-checks before decoding, as defence in depth.
export const IMAGE_MAX_PIXELS = 16_777_216;
export const IMAGE_MAX_SIDE = 8192;

// The coarse classifications `SensitiveClassification` returns (daemon
// `files/policy.go`). Anything else under FILE_DENIED is an access verdict.
const SENSITIVE_REASONS = new Set([
  "dotenv",
  "private_key",
  "keystore",
  "sensitive_dir",
  "sensitive",
]);

/** The states that render in the denial pane, each with its own next step. */
export type BinaryDenialState =
  | "cancelled"
  | "denied_sensitive"
  | "denied_access"
  | "permission"
  | "too_large"
  | "limit"
  | "invalid"
  | "changed"
  | "unsupported"
  | "render_failed"
  | "unsupported_browser"
  | "offline"
  | "forbidden"
  | "busy"
  | "transfer_failed"
  | "session_ended";

export type BinaryPreviewState =
  | "idle"
  | "loading"
  | "ready"
  // Central says this node's live connection does not preview (it reconnected
  // with the switch off, or the flag went off). Not a user-facing state: the
  // pane falls back to the text path, which shows the existing FILE_BINARY
  // pane, exactly as a capability of false would.
  | "node_unsupported"
  | BinaryDenialState;

export interface BinaryPreviewDetail {
  reason?: string;
  size?: number;
  limit?: number;
}

// In-flight controllers across every owner, for the leak gate. Outside any
// reactive state for the same reason as the files store's.
const inflight = new Set<AbortController>();
/** Test seam: requests still running. Must be 0 after every disposal. */
export function binaryPreviewInflightCount(): number {
  return inflight.size;
}

// The client-side verdict for a preview body that did not arrive exactly as
// declared. Not a server code — nothing on the wire carries it — and shown as
// "the transfer failed, try again".
export const PREVIEW_TRANSFER_FAILED = "PREVIEW_TRANSFER_FAILED";
function transferFailed(): ApiError {
  return new ApiError(
    PREVIEW_TRANSFER_FAILED,
    "The preview did not arrive intact",
    0,
  );
}

// ADR 0029 §2 (the allowlist) and §4 (the per-kind size ceilings), rechecked on
// the response headers, which are the only statement of what the body is. A
// body is buffered only once they say something coherent.
const KIND_BY_MIME: Record<BinaryPreviewMime, BinaryPreviewKind> = {
  "image/png": "image",
  "image/jpeg": "image",
  "image/webp": "image",
  "image/gif": "image",
  "application/pdf": "pdf",
};
const MAX_BYTES: Record<BinaryPreviewKind, number> = {
  image: 8 * 1024 * 1024,
  pdf: 16 * 1024 * 1024,
};

function headerInt(headers: Headers, name: string): number | undefined {
  const raw = headers.get(name);
  if (raw === null || !/^[0-9]{1,10}$/.test(raw)) return undefined;
  return Number(raw);
}

function previewMeta(headers: Headers): BinaryPreviewMeta | null {
  const mime = headers.get("x-cliora-preview-mime") as BinaryPreviewMime | null;
  const kind = mime ? KIND_BY_MIME[mime] : undefined;
  const size = headerInt(headers, "content-length");
  if (
    !mime ||
    !kind ||
    headers.get("x-cliora-preview-kind") !== kind ||
    size === undefined ||
    size < 1 ||
    size > MAX_BYTES[kind]
  ) {
    return null;
  }
  if (kind === "pdf") return { kind, mime, size };
  const width = headerInt(headers, "x-cliora-preview-width");
  const height = headerInt(headers, "x-cliora-preview-height");
  // Present and positive only; the pixel and side limits are re-checked by the
  // renderer, which reports them as their own state.
  if (width === undefined || height === undefined || width < 1 || height < 1) {
    return null;
  }
  return { kind, mime, size, width, height };
}

/**
 * Read a preview response into one buffer of exactly the declared size
 * (plan/31/05 BP-06 §2). Anything else — a stream cut short, one that keeps
 * going, a size over the kind's ceiling, a type outside the allowlist — throws
 * and yields no bytes at all, so a truncated file never reaches a decoder.
 */
export async function readPreviewBody(
  res: Response,
  onProgress?: (received: number, total: number) => void,
): Promise<BinaryPreviewPayload> {
  const meta = previewMeta(res.headers);
  const body = res.body;
  if (!meta || !body) {
    await body?.cancel().catch(() => undefined);
    throw transferFailed();
  }
  const bytes = new Uint8Array(meta.size);
  const reader = body.getReader();
  let received = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (received + value.byteLength > meta.size) throw transferFailed();
      bytes.set(value, received);
      received += value.byteLength;
      onProgress?.(received, meta.size);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    if (isAbortError(error) || error instanceof ApiError) throw error;
    // A connection lost mid-body surfaces as a TypeError from `read()`.
    throw transferFailed();
  }
  if (received !== meta.size) throw transferFailed();
  return { meta, bytes };
}

function num(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

// Map a refusal onto a state. Each code keeps its own state because each has
// a different next step; the mapping reads only the code, the status and the
// server's coarse `details` — never its prose.
export function classifyPreviewError(error: unknown): {
  state: Exclude<BinaryPreviewState, "idle" | "loading" | "ready">;
  detail: BinaryPreviewDetail;
} {
  if (!(error instanceof ApiError)) {
    return { state: "transfer_failed", detail: {} };
  }
  const reason =
    typeof error.details?.reason === "string"
      ? error.details.reason
      : undefined;
  const detail: BinaryPreviewDetail = {
    reason,
    size: num(error.details?.size),
    limit: num(error.details?.limit),
  };
  switch (error.code) {
    case "FILE_DENIED":
      return {
        state:
          reason && SENSITIVE_REASONS.has(reason)
            ? "denied_sensitive"
            : "denied_access",
        detail: {},
      };
    case "FILE_NOT_FOUND":
    case "INVALID_ARGUMENT":
      return { state: "denied_access", detail: {} };
    case "FILE_PERMISSION_DENIED":
      return { state: "permission", detail: {} };
    case "FILE_TOO_LARGE":
      return { state: "too_large", detail };
    case "FILE_PREVIEW_LIMIT":
      return { state: "limit", detail };
    case "FILE_PREVIEW_INVALID":
      return {
        state: reason === "changed" ? "changed" : "invalid",
        detail,
      };
    case "FILE_PREVIEW_UNSUPPORTED":
      return { state: "unsupported", detail };
    case "FILE_PREVIEW_UNSUPPORTED_NODE":
    case "FILE_PREVIEW_DISABLED":
      return { state: "node_unsupported", detail: {} };
    case "NODE_OFFLINE":
      return { state: "offline", detail: {} };
    case "FILE_PREVIEW_BUSY":
    case "NODE_BUSY":
      return { state: "busy", detail: {} };
  }
  if (error.status === 429) return { state: "busy", detail: {} };
  if (error.status === 401 || error.status === 403) {
    return { state: "forbidden", detail: {} };
  }
  // FILE_PREVIEW_EXPIRED, REQUEST_TIMEOUT, a short body, a lost connection.
  return { state: "transfer_failed", detail: {} };
}

function imageLimit(
  width: number | undefined,
  height: number | undefined,
): "pixels" | "dimensions" | null {
  if (!width || !height) return "dimensions";
  if (width > IMAGE_MAX_SIDE || height > IMAGE_MAX_SIDE) return "dimensions";
  if (width * height > IMAGE_MAX_PIXELS) return "pixels";
  return null;
}

function formatMiB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Progress is announced politely and at most this often, so a screen reader
// says "40%" rather than reading out every chunk.
const ANNOUNCE_EVERY_MS = 1500;

export interface BinaryPreviewOptions {
  /** The session on screen. A change disposes everything, synchronously. */
  sessionId: Ref<string | null>;
  /** `can_preview_binary`. Becoming false disposes, synchronously. */
  enabled: Ref<boolean>;
}

export function useBinaryPreview(options: BinaryPreviewOptions) {
  const store = useBinaryPreviewStore();
  const auth = useAuthStore();

  const state = ref<BinaryPreviewState>("idle");
  const detail = ref<BinaryPreviewDetail>({});
  const meta = shallowRef<BinaryPreviewMeta | null>(null);
  const bitmap = shallowRef<ImageBitmap | null>(null);
  const progress = ref({ received: 0, total: 0 });
  const announcement = ref("");
  const currentPath = ref<string | null>(null);

  let controller: AbortController | null = null;
  // Bumped by every abort, so an `await` that resumes after one can tell.
  let generation = 0;
  let disposed = false;
  let lastAnnounced = 0;
  const canvases = new Set<HTMLCanvasElement>();

  function abortInflight(): void {
    generation += 1;
    if (controller) {
      controller.abort();
      inflight.delete(controller);
      controller = null;
    }
  }

  // Everything that holds pixels, in the ADR 0029 §14 order after the abort.
  function releaseContent(): void {
    bitmap.value?.close();
    bitmap.value = null;
    for (const canvas of canvases) {
      canvas.width = 0;
      canvas.height = 0;
    }
    meta.value = null;
    store.meta = null;
  }

  function disposeAll(): void {
    abortInflight();
    releaseContent();
    currentPath.value = null;
    detail.value = {};
    progress.value = { received: 0, total: 0 };
    announcement.value = "";
    state.value = "idle";
  }

  function onProgress(received: number, total: number): void {
    progress.value = { received, total };
    const now = Date.now();
    if (received === total || now - lastAnnounced >= ANNOUNCE_EVERY_MS) {
      lastAnnounced = now;
      announcement.value = `已接收 ${formatMiB(received)}／${formatMiB(total)}`;
    }
  }

  async function paintImage(
    payload: BinaryPreviewPayload,
    stale: () => boolean,
  ): Promise<void> {
    const m = payload.meta;
    const limit = imageLimit(m.width, m.height);
    if (limit) {
      state.value = "limit";
      detail.value = { reason: limit };
      return;
    }
    let decoded: ImageBitmap;
    try {
      decoded = await createImageBitmap(
        new Blob([payload.bytes], { type: m.mime }),
        { imageOrientation: "from-image" },
      );
    } catch {
      if (!stale()) state.value = "render_failed";
      return;
    }
    if (stale()) {
      decoded.close();
      return;
    }
    // EXIF rotation can swap the sides; re-check what was actually decoded.
    const decodedLimit = imageLimit(decoded.width, decoded.height);
    if (decodedLimit) {
      decoded.close();
      state.value = "limit";
      detail.value = { reason: decodedLimit };
      return;
    }
    bitmap.value = markRaw(decoded);
    meta.value = m;
    store.meta = m;
    state.value = "ready";
  }

  async function open(relPath: string): Promise<void> {
    if (disposed) return;
    // 先清再換: nothing of the previous file survives into this one.
    abortInflight();
    releaseContent();
    currentPath.value = relPath;
    detail.value = {};
    progress.value = { received: 0, total: 0 };
    announcement.value = "";

    const sessionId = options.sessionId.value;
    if (!sessionId) {
      // No request for a session that is over: a retry would only fail.
      state.value = "session_ended";
      return;
    }
    if (typeof globalThis.createImageBitmap !== "function") {
      state.value = "unsupported_browser";
      return;
    }

    const request = new AbortController();
    controller = request;
    inflight.add(request);
    const ticket = generation;
    const stale = () =>
      disposed ||
      ticket !== generation ||
      options.sessionId.value !== sessionId ||
      currentPath.value !== relPath;
    state.value = "loading";
    announcement.value = "正在載入預覽";

    try {
      const response = await api().fetchBinaryPreview(sessionId, relPath, {
        signal: request.signal,
      });
      if (stale()) {
        await response.body?.cancel().catch(() => undefined);
        return;
      }
      const payload = await readPreviewBody(response, (received, total) => {
        if (!stale()) onProgress(received, total);
      });
      // A late answer for another session, file or user: dropped unread.
      if (stale()) return;
      if (payload.meta.kind !== "image") {
        state.value = "render_failed";
        return;
      }
      await paintImage(payload, stale);
    } catch (caught) {
      if (isAbortError(caught) || stale()) return;
      const verdict = classifyPreviewError(caught);
      state.value = verdict.state;
      detail.value = verdict.detail;
    } finally {
      inflight.delete(request);
      if (controller === request) controller = null;
    }
  }

  async function retry(): Promise<void> {
    if (currentPath.value) await open(currentPath.value);
  }

  // The user's cancel: the transfer stops, nothing is shown as an error.
  function cancel(): void {
    const wasLoading = state.value === "loading";
    abortInflight();
    if (wasLoading) state.value = "cancelled";
  }

  function close(): void {
    disposeAll();
  }

  /** Hand a canvas to the owner, which zeroes it on every disposal. */
  function registerCanvas(canvas: HTMLCanvasElement): () => void {
    canvases.add(canvas);
    return () => {
      canvases.delete(canvas);
    };
  }

  function dispose(): void {
    if (disposed) return;
    disposeAll();
    disposed = true;
  }

  // Session change: cleared in the same call, before B can render anything.
  watch(options.sessionId, () => disposeAll(), { flush: "sync" });
  // Capability gone (flag off, node reconnected without it): same.
  watch(
    options.enabled,
    (enabled) => {
      if (!enabled) disposeAll();
    },
    { flush: "sync" },
  );
  // Identity unconfirmed (a cross-tab token swap): stop what is in flight, keep
  // what is on screen — `/me` may name the same user. Sign-out and a user
  // change are the auth-loss handler's, through the store's `clear()`.
  watch(
    () => auth.identityPending,
    (pending) => {
      if (!pending) return;
      const wasLoading = state.value === "loading";
      abortInflight();
      if (wasLoading) state.value = "cancelled";
    },
    { flush: "sync" },
  );

  const unregister = registerBinaryPreviewOwner(disposeAll);
  onScopeDispose(() => {
    dispose();
    unregister();
  });

  return {
    state,
    detail,
    meta,
    bitmap,
    progress,
    announcement,
    currentPath,
    open,
    retry,
    cancel,
    close,
    dispose,
    registerCanvas,
  };
}

export type BinaryPreview = ReturnType<typeof useBinaryPreview>;
