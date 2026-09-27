import { onScopeDispose, ref } from "vue";

import { ApiError, isAbortError } from "../api/client";

// Workspace file download (FD-06, ADR 0028). One verb, one composable, and the
// asymmetry with `useFileUpload` next door is not an oversight: upload has a
// queue because a user drops several files at once and each one can fail
// differently, while download is started by clicking one file and there is
// nothing to reconcile afterwards. A queue here would be machinery with no
// question to answer.
//
// What it does own is the part that is easy to get wrong in a browser: an object
// URL that must be revoked, an in-flight request that must be abortable, and a
// failure that has to be expressed as a message rather than a thrown promise
// nobody catches.

export type DownloadState = "idle" | "downloading" | "error";

export type FileDownloader = (
  path: string,
  signal: AbortSignal,
) => Promise<{ blob: Blob; filename: string }>;

// What the browser is asked to do with the bytes once they arrive. Injectable so
// the unit test can assert the anchor-and-revoke dance without a real DOM
// download, which jsdom does not perform.
export type FileSaver = (blob: Blob, filename: string) => void;

// The default saver. `URL.revokeObjectURL` is the load-bearing line: without it
// every download leaks its whole blob for the lifetime of the tab, which on a
// path with a 4 MiB ceiling is measured in tens of megabytes over a session.
//
// The revoke is deferred rather than immediate because Safari and older Firefox
// abort the save if the URL disappears in the same task as the click.
function saveViaAnchor(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// Codes whose message is worth showing verbatim, because each one has a different
// next step and the server already phrased it for a user. Anything else collapses
// to one sentence: a stack of distinct internal failures reading differently
// teaches people to read none of them.
const SPOKEN_CODES = new Set([
  "FILE_DENIED",
  "FILE_TOO_LARGE",
  "FILE_NOT_FOUND",
  "FILE_PERMISSION_DENIED",
  "FILE_DOWNLOAD_DISABLED",
  "NODE_OFFLINE",
]);

export function useFileDownload(
  download: FileDownloader,
  save: FileSaver = saveViaAnchor,
) {
  const state = ref<DownloadState>("idle");
  // The path currently being fetched, so a row can show its own spinner rather
  // than the whole tree showing one.
  const activePath = ref<string | null>(null);
  const errorMessage = ref("");
  let controller: AbortController | null = null;

  function cancel(): void {
    controller?.abort();
    controller = null;
  }

  // Leaving the view mid-download must not leave the request running: the
  // response is a file, so an orphaned one is 4 MiB nobody will ever look at.
  onScopeDispose(cancel);

  async function start(path: string): Promise<boolean> {
    // One at a time. A second click supersedes the first rather than racing it,
    // because two concurrent saves of different files is not what a double click
    // means.
    cancel();
    controller = new AbortController();
    const mine = controller;
    state.value = "downloading";
    activePath.value = path;
    errorMessage.value = "";
    try {
      const { blob, filename } = await download(path, mine.signal);
      // A superseded request must not save its bytes over the newer one's.
      if (controller !== mine) return false;
      save(blob, filename);
      state.value = "idle";
      activePath.value = null;
      return true;
    } catch (caught) {
      if (isAbortError(caught) || controller !== mine) {
        // Cancelled or superseded: not an error, and leaving an error state
        // behind would make the newer download look broken.
        //
        // The two cases are told apart by what `controller` now holds, and the
        // distinction is load-bearing. `cancel()` sets it to null and nothing
        // else is coming, so this call still owns the visible state and has to
        // reset it — otherwise an explicit cancel leaves the spinner running
        // forever. A newer `start()` sets it to that call's controller, which
        // already set the state to "downloading" for its own path, so touching
        // it here would clear a spinner that is still true.
        if (controller === null || controller === mine) {
          state.value = "idle";
          activePath.value = null;
        }
        return false;
      }
      state.value = "error";
      activePath.value = null;
      errorMessage.value = messageFor(caught);
      return false;
    } finally {
      if (controller === mine) controller = null;
    }
  }

  function clearError(): void {
    errorMessage.value = "";
    if (state.value === "error") state.value = "idle";
  }

  return { state, activePath, errorMessage, start, cancel, clearError };
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403 && !SPOKEN_CODES.has(error.code)) {
      return "你的角色沒有下載這個工作區檔案的權限。";
    }
    if (SPOKEN_CODES.has(error.code)) return error.message;
  }
  return "無法下載這個檔案。";
}
