import { onScopeDispose, readonly, ref } from "vue";

import { ApiError } from "../api/client";
import type { FileUploadResult } from "../api/dto";

// Image drop (WF-07, ADR 0024). Three entry points — paste, drag-and-drop, file
// picker — that all funnel into one `submit`, so there is one code path to
// reason about and one to test.
//
// The composable owns the upload and the preview thumbnail; inserting the
// returned path into the terminal is the caller's job, because only the caller
// knows which terminal is in front of the user.

// The four types a CLI can read. Checked here as well as on the server so a
// 20 MiB PSD is refused before it is uploaded, not after.
export const ACCEPTED_IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
] as const;

export const MAX_IMAGE_BYTES = 4 * 1024 * 1024;

export type UploadState = "idle" | "uploading" | "done" | "error";

export interface DroppedImage {
  // The user's own filename, kept only as a label. It never reaches the wire:
  // the daemon names the stored file (ADR 0024 §3).
  label: string;
  // Object URL for the local thumbnail. Revoked on clear/dispose — a 4 MiB blob
  // that is never revoked lives until the tab closes, and users drop many.
  previewUrl: string;
  storedPath?: string;
}

export type ImageUploader = (
  file: File,
  onProgress: (fraction: number) => void,
  signal: AbortSignal,
) => Promise<FileUploadResult>;

export function useImageDrop(upload: ImageUploader) {
  const state = ref<UploadState>("idle");
  const progress = ref(0);
  const current = ref<DroppedImage | null>(null);
  const errorCode = ref<string>();
  const errorMessage = ref<string>();
  let controller: AbortController | undefined;

  function revoke(): void {
    if (current.value) {
      URL.revokeObjectURL(current.value.previewUrl);
    }
  }

  function clear(): void {
    revoke();
    current.value = null;
    state.value = "idle";
    progress.value = 0;
    errorCode.value = undefined;
    errorMessage.value = undefined;
  }

  function fail(code: string, message: string): null {
    errorCode.value = code;
    errorMessage.value = message;
    state.value = "error";
    return null;
  }

  function accepts(file: File): boolean {
    return (ACCEPTED_IMAGE_TYPES as readonly string[]).includes(file.type);
  }

  /**
   * Upload one image. Resolves to the stored workspace-relative path, or null
   * when the drop was refused or failed — the caller checks for null rather
   * than catching, because a refusal is a normal outcome here.
   */
  async function submit(file: File): Promise<string | null> {
    revoke();
    errorCode.value = undefined;
    errorMessage.value = undefined;
    if (!accepts(file)) {
      current.value = null;
      return fail(
        "FILE_UPLOAD_UNSUPPORTED_TYPE",
        "僅支援 PNG、JPEG、GIF 與 WebP 圖片。",
      );
    }
    if (file.size > MAX_IMAGE_BYTES) {
      current.value = null;
      return fail("FILE_UPLOAD_TOO_LARGE", "圖片超過 4 MiB 上限。");
    }
    current.value = {
      label: file.name || "image",
      previewUrl: URL.createObjectURL(file),
    };
    state.value = "uploading";
    progress.value = 0;
    controller?.abort();
    controller = new AbortController();
    try {
      const result = await upload(
        file,
        (fraction) => {
          progress.value = fraction;
        },
        controller.signal,
      );
      current.value = { ...current.value, storedPath: result.path };
      state.value = "done";
      progress.value = 1;
      return result.path;
    } catch (error) {
      const api = error instanceof ApiError ? error : undefined;
      if (api?.code === "CANCELLED") {
        clear();
        return null;
      }
      return fail(api?.code ?? "HTTP_ERROR", api?.message ?? "圖片上傳失敗。");
    }
  }

  /**
   * Paste handler, for the CAPTURE phase on the terminal host.
   *
   * Measured against @xterm/xterm 5.5.0: its own handler calls
   * `stopPropagation()` on the helper textarea, so a bubble-phase listener on an
   * ancestor never runs — capture on the host is the only place this can sit.
   * It also reads only `getData("text/plain")`, which is empty for an
   * image-only paste, so today Ctrl+V with an image does nothing at all.
   *
   * Only takes over when the clipboard actually carries files. Ordinary text
   * paste is used constantly, and breaking it would be far worse than not
   * having image drop.
   */
  function handlePaste(event: ClipboardEvent): File | null {
    const files = event.clipboardData?.files;
    if (!files || files.length === 0) return null;
    const image = Array.from(files).find((f) => f.type.startsWith("image/"));
    if (!image) return null;
    event.preventDefault();
    event.stopPropagation();
    return image;
  }

  function handleDrop(event: DragEvent): File | null {
    const files = event.dataTransfer?.files;
    if (!files || files.length === 0) return null;
    const image = Array.from(files).find((f) => f.type.startsWith("image/"));
    if (!image) return null;
    event.preventDefault();
    return image;
  }

  function cancel(): void {
    controller?.abort();
  }

  onScopeDispose(() => {
    controller?.abort();
    revoke();
  });

  return {
    submit,
    handlePaste,
    handleDrop,
    clear,
    cancel,
    accepts,
    state: readonly(state),
    progress: readonly(progress),
    current: readonly(current),
    errorCode: readonly(errorCode),
    errorMessage: readonly(errorMessage),
  };
}
