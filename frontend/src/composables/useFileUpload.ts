import { onScopeDispose, readonly, ref } from "vue";

import { ApiError } from "../api/client";
import type { FileStoreResult } from "../api/dto";

// General file upload (FU-06, ADR 0026). Two entry points — dropping onto a row
// of the file tree, and the toolbar's file picker — funnelling into one `submit`,
// the same shape `useImageDrop` established: one code path to reason about and
// one to test.
//
// The composable owns the queue and its per-file state. Choosing the destination
// belongs to the caller, because only the caller knows which row the user aimed
// at, and refreshing the tree afterwards belongs to the caller for the same
// reason.

// Shared with image drop by way of the node's single `filesystem.upload.max_bytes`
// key: one ceiling for both paths, so they cannot disagree about what fits in a
// frame. Checked here too so a 20 MiB archive is refused before it is uploaded
// rather than after.
export const MAX_FILE_BYTES = 4 * 1024 * 1024;

// The longest filename the node will store, in BYTES. Not characters: 84 CJK
// characters plus an extension is 88 characters and 256 bytes, and the wire
// schema's maxLength counts characters (measured:
// plan/15/07-open-measurements.md §2).
export const MAX_FILENAME_BYTES = 255;

// A bound on one drop, so that dragging a whole downloads folder in produces one
// clear refusal instead of two hundred requests.
export const MAX_BATCH = 20;

export type UploadItemState = "queued" | "uploading" | "done" | "error";

export interface UploadItem {
  // Stable across the item's life so a list render does not reorder mid-upload.
  id: string;
  name: string;
  directory: string;
  size: number;
  state: UploadItemState;
  progress: number;
  // Set once the node has stored it: the path the file actually landed at.
  storedPath?: string;
  errorCode?: string;
  errorMessage?: string;
  // Carried so a rename can retry the same bytes without asking the user to pick
  // the file again.
  file: File;
}

export type FileUploader = (
  directory: string,
  filename: string,
  file: File,
  onProgress: (fraction: number) => void,
  signal: AbortSignal,
) => Promise<FileStoreResult>;

export interface BatchOutcome {
  // Directories that gained a file, so the caller knows what to refresh — once,
  // after the batch, rather than once per file.
  touched: string[];
  succeeded: number;
  failed: number;
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

/** Refusal reason for a filename, or "" if it is storable. Mirrors the daemon's
 * own check; Central checks too. Three layers is not redundancy here — this one
 * exists so the user is told before the bytes leave the browser. */
export function filenameRefusal(name: string): string {
  if (!name) return "檔名不可為空";
  if (name === "." || name === "..") return "檔名不可為 . 或 ..";
  if (name.includes("/")) return "檔名不可包含 /";
  if (byteLength(name) > MAX_FILENAME_BYTES)
    return "檔名過長（上限 255 位元組）";
  for (const ch of name) {
    const code = ch.codePointAt(0) ?? 0;
    if (code < 0x20 || code === 0x7f) return "檔名不可包含控制字元";
  }
  return "";
}

/** A suggested non-colliding name for a retry: `data.csv` → `data-2.csv`.
 *
 * Deliberately not checked against the server first — that would cost a round
 * trip to avoid seeing the same error twice, and the user can read the suggestion
 * before sending it. */
export function suggestRename(name: string, attempt = 2): string {
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  return `${stem}-${attempt}${ext}`;
}

/** Extract the files from a drop, or a refusal reason.
 *
 * The rule is **positive confirmation**: every item must be identifiable as a
 * file, and anything else refuses the whole batch. That is stricter than
 * "detect directories and reject them", and deliberately so — the behaviour of
 * `webkitGetAsEntry` could not be measured in the environment this was built in
 * (plan/15/07-open-measurements.md §1), so the code does not depend on it being
 * true. If the probe later confirms it, this rule is already correct and needs no
 * relaxing.
 *
 * Refusing the batch rather than silently skipping the folders matters: a user
 * who drags a folder and sees three of its files upload will believe the folder
 * uploaded. */
export function filesFromDrop(transfer: DataTransfer | null): {
  files: File[];
  refusal: string;
} {
  if (!transfer) return { files: [], refusal: "沒有可上傳的檔案" };
  const items = transfer.items;
  if (!items || items.length === 0) {
    // No `items` at all means nothing can be confirmed. The picker path does not
    // come through here (a plain file input cannot select a directory), so this is
    // a drop we do not understand.
    return { files: [], refusal: "無法辨識拖放的內容，請改用「上傳檔案」按鈕" };
  }
  const files: File[] = [];
  for (const item of Array.from(items)) {
    if (item.kind !== "file") continue;
    const entry =
      typeof item.webkitGetAsEntry === "function"
        ? item.webkitGetAsEntry()
        : null;
    if (!entry || !entry.isFile) {
      return {
        files: [],
        refusal: "資料夾請用終端機處理（git clone／scp／tar）",
      };
    }
    const file = item.getAsFile();
    if (!file) {
      return { files: [], refusal: "無法讀取拖放的檔案" };
    }
    files.push(file);
  }
  if (files.length === 0) return { files: [], refusal: "沒有可上傳的檔案" };
  return { files, refusal: "" };
}

export function useFileUpload(upload: FileUploader) {
  const items = ref<UploadItem[]>([]);
  const busy = ref(false);
  // A refusal that applies to the whole drop rather than to one file (a folder, an
  // unreadable transfer, more than MAX_BATCH files).
  const batchRefusal = ref("");
  let controller: AbortController | undefined;
  let seq = 0;

  function clear(): void {
    items.value = [];
    batchRefusal.value = "";
  }

  function dismiss(id: string): void {
    items.value = items.value.filter((item) => item.id !== id);
  }

  function cancel(): void {
    controller?.abort();
  }

  /** Upload `files` into `directory`, one at a time.
   *
   * Sequential rather than concurrent: `filesystem.store` is a large-frame type on
   * the node's single control connection, and twenty 4 MiB uploads in parallel
   * would block it for everything else on that node.
   */
  async function submit(
    files: File[],
    directory: string,
  ): Promise<BatchOutcome> {
    batchRefusal.value = "";
    let queue = files;
    if (queue.length > MAX_BATCH) {
      queue = queue.slice(0, MAX_BATCH);
      batchRefusal.value = `一次最多 ${MAX_BATCH} 個檔案，只處理前 ${MAX_BATCH} 個`;
    }

    const queued: UploadItem[] = queue.map((file) => {
      seq += 1;
      const item: UploadItem = {
        id: `u${seq}`,
        name: file.name,
        directory,
        size: file.size,
        state: "queued",
        progress: 0,
        file,
      };
      // Local pre-checks, so a 20 MiB archive or an impossible name is refused
      // without a request. Marked rather than dropped: a file that silently
      // vanishes from the list reads as a bug.
      const nameProblem = filenameRefusal(file.name);
      if (nameProblem) {
        item.state = "error";
        item.errorCode = "FILE_INVALID_NAME";
        item.errorMessage = nameProblem;
      } else if (file.size > MAX_FILE_BYTES) {
        item.state = "error";
        item.errorCode = "FILE_UPLOAD_TOO_LARGE";
        item.errorMessage = "超過 4 MiB 上限，較大的檔案請在節點上以終端機處理";
      }
      return item;
    });
    items.value = [...items.value, ...queued];

    const outcome: BatchOutcome = { touched: [], succeeded: 0, failed: 0 };
    busy.value = true;
    controller = new AbortController();
    try {
      for (const item of queued) {
        if (item.state === "error") {
          outcome.failed += 1;
          continue;
        }
        await run(item, outcome);
      }
    } finally {
      busy.value = false;
      controller = undefined;
    }
    return outcome;
  }

  async function run(item: UploadItem, outcome: BatchOutcome): Promise<void> {
    const signal = controller?.signal ?? new AbortController().signal;
    patch(item.id, { state: "uploading", progress: 0 });
    try {
      const result = await upload(
        item.directory,
        item.name,
        item.file,
        (fraction) => patch(item.id, { progress: fraction }),
        signal,
      );
      patch(item.id, { state: "done", progress: 1, storedPath: result.path });
      outcome.succeeded += 1;
      if (!outcome.touched.includes(item.directory)) {
        outcome.touched.push(item.directory);
      }
    } catch (error) {
      const code = error instanceof ApiError ? error.code : "NETWORK_ERROR";
      patch(item.id, {
        state: "error",
        errorCode: code,
        errorMessage: describe(error),
      });
      outcome.failed += 1;
    }
  }

  /** Retry one failed item under a new name, keeping the same bytes. This is the
   * whole of the collision flow: upload never overwrites, so the answer to
   * FILE_EXISTS is a different name (ADR 0026 §3). */
  async function retryAs(id: string, filename: string): Promise<BatchOutcome> {
    const existing = items.value.find((item) => item.id === id);
    if (!existing) return { touched: [], succeeded: 0, failed: 0 };
    dismiss(id);
    const renamed = new File([existing.file], filename, {
      type: existing.file.type,
    });
    return submit([renamed], existing.directory);
  }

  function patch(id: string, changes: Partial<UploadItem>): void {
    items.value = items.value.map((item) =>
      item.id === id ? { ...item, ...changes } : item,
    );
  }

  onScopeDispose(() => controller?.abort());

  return {
    items: readonly(items),
    busy: readonly(busy),
    batchRefusal: readonly(batchRefusal),
    submit,
    retryAs,
    dismiss,
    clear,
    cancel,
  };
}

/** User-facing text for an upload failure. Every branch names a next step, or
 * says plainly that there is none — an error without one gets reported as a bug. */
export function describe(error: unknown): string {
  if (!(error instanceof ApiError)) return "上傳失敗，請稍後再試";
  switch (error.code) {
    case "FILE_EXISTS":
      return "這個目錄裡已經有同名的項目。請改名，或在節點上以終端機取代它";
    case "FILE_UPLOAD_TOO_LARGE":
      return "超過 4 MiB 上限，較大的檔案請在節點上以終端機處理";
    case "FILE_UPLOAD_QUOTA_EXCEEDED":
      return "這個 Session 的上傳用量已達上限，請稍後再試或聯絡管理者";
    case "FILE_UPLOAD_NO_SPACE":
      return "節點磁碟空間不足，請通知管理者";
    case "FILE_UPLOAD_DISABLED":
      return "這個節點停用了檔案上傳";
    case "FILE_INVALID_NAME":
      return "檔名不可包含 / 或控制字元";
    case "FILE_INVALID_PATH":
      return "目標目錄無效，請重新整理檔案樹";
    case "FILE_NOT_FOUND":
      return "目標目錄不存在或已改變，請重新整理檔案樹";
    case "FILE_DENIED":
      return "這個位置或檔名不開放上傳（例如 git 內部檔案、平台目錄或受保護的名稱）";
    case "CANCELLED":
      return "已取消";
    default:
      if (error.status === 403) return "沒有上傳檔案的權限";
      return error.message || "上傳失敗，請稍後再試";
  }
}
