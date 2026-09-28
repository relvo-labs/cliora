// The binary preview's public reset, for owners that are not components
// (ADR 0029 §14, plan/31/05 BP-06 §3).
//
// The bytes, the decoded bitmap, the PDF document and every canvas belong to
// `useBinaryPreview` alone, and none of them is reactive state. What lives here
// is what the auth-loss handler needs to reach them: `clear()`, which disposes
// whatever preview is open in the same synchronous call, plus the metadata of
// what is on screen (kind, type, size, dimensions — never a path or a byte).

import { defineStore } from "pinia";

import type { BinaryPreviewMeta } from "../api/dto";

// Registered disposers, outside the reactive state for the same reason the
// files store keeps its AbortControllers there: plumbing, not data. A Set rather
// than one slot, so a pane that mounts before the previous one has unmounted
// (a width change) cannot unregister its successor.
const owners = new Set<() => void>();

/** Called by the preview's owner; returns its own unregister. */
export function registerBinaryPreviewOwner(dispose: () => void): () => void {
  owners.add(dispose);
  return () => {
    owners.delete(dispose);
  };
}

export const useBinaryPreviewStore = defineStore("binaryPreview", {
  state: () => ({
    meta: null as BinaryPreviewMeta | null,
  }),
  actions: {
    // Dispose every open preview now: abort, cancel renders, destroy the PDF,
    // close the bitmap, zero the canvases, drop the bytes. Synchronous, so the
    // auth-loss watcher (flush: "sync") clears the screen before anything
    // else can render.
    clear(): void {
      for (const dispose of [...owners]) dispose();
      this.meta = null;
    },
  },
});
