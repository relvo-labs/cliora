<script setup lang="ts">
// "Cannot preview" pane. Every denial states what happened, why, and what the
// user can do next — in text, not colour alone. It never renders a content
// fragment, a MIME-typed body, or a server absolute path (SEC-004).

import {
  Ban,
  CircleStop,
  CircleX,
  FileQuestion,
  FileType,
  FileWarning,
  Files,
  HardDrive,
  Hourglass,
  ImageOff,
  KeyRound,
  Lock,
  MonitorX,
  RefreshCw,
  Scaling,
  ShieldAlert,
  Unplug,
  WifiOff,
} from "lucide-vue-next";
import { computed, type Component } from "vue";

import type {
  BinaryDenialState,
  BinaryPreviewDetail,
} from "../../composables/useBinaryPreview";
import type { PreviewDenial } from "../../composables/useMonacoModel";

const props = defineProps<{
  // The text path's verdict (FILE_BINARY, FILE_TOO_LARGE, …). Unchanged.
  denial?: PreviewDenial;
  // The binary preview's state (ADR 0029, plan/31/05 BP-06 §4). A separate
  // branch with its own copy: none of these states offers to hand the file
  // over instead, including the ones where the file was refused as unsafe
  // (ADR 0029 §16, T16).
  binary?: { state: BinaryDenialState; detail: BinaryPreviewDetail };
  relPath: string;
  // Whether download is available at all here (permission AND the node's own
  // report, resolved upstairs). This pane is the most useful place it can appear:
  // a binary file is precisely the case where "show it" was never the question.
  canDownload?: boolean;
  downloading?: boolean;
}>();
const emit = defineEmits<{
  refresh: [];
  download: [];
  // Binary branch only.
  retry: [];
  text: [];
  "refresh-list": [];
}>();

// The download ceiling, in bytes. Larger than the 2 MiB preview cap, which is why
// FILE_TOO_LARGE is not one verdict but two: a 3 MiB file cannot be previewed and
// can be downloaded, and telling that user to go and use a terminal would be
// wrong (ADR 0028 §3).
const MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024;

// Coarse classifications the daemon may attach to FILE_DENIED (never a path).
const REASONS: Record<string, string> = {
  dotenv: "環境變數檔（.env 類）",
  private_key: "私鑰檔",
  keystore: "金鑰庫檔（p12/pfx）",
  sensitive_dir: "位於敏感目錄下",
  sensitive: "敏感檔案類型",
  not_regular: "不是一般檔案（目錄、裝置或 socket）",
  outside_root: "不在允許的工作區範圍內",
  unresolved: "無法確認實際檔案位置",
  invalid: "路徑格式無效",
  not_found: "檔案不存在",
  unsupported_encoding: "不是 UTF-8 編碼（例如 Big5、GBK、UTF-16）",
};

function formatBytes(size: number | undefined): string {
  if (size === undefined) {
    return "未知大小";
  }
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

interface View {
  icon: Component;
  title: string;
  detail: string;
  next: string;
  offerDownload: boolean;
  // Binary branch only: the one action that can help, if any.
  action?: { label: string; emit: "retry" | "text" | "refresh-list" };
}

const LIMIT_DETAIL: Record<string, string> = {
  pixels: "圖片的像素數超過預覽上限（最多 16,777,216 像素）。",
  dimensions: "圖片的邊長超過預覽上限（最長 8192 像素）。",
  complexity: "檔案結構過於複雜：中繼資料、影格或掃描次數超過預覽上限。",
};

// One entry per state, each with its own next step (plan/31/05 BP-06 §4). No
// entry offers download or save: `offerDownload` is false throughout, and the
// copy does not suggest taking the file elsewhere as a way around a refusal.
function binaryView(state: BinaryDenialState, d: BinaryPreviewDetail): View {
  const base = { offerDownload: false };
  switch (state) {
    case "cancelled":
      return {
        ...base,
        icon: CircleX,
        title: "已取消載入",
        detail: "沒有顯示任何內容。",
        next: "回到檔案清單選擇其他檔案，或重新載入這一個。",
        action: { label: "重新載入", emit: "retry" },
      };
    case "denied_sensitive":
      // Nothing about the classification or the resolved name: the file is
      // protected, and which rule protected it is not the viewer's business.
      return {
        ...base,
        icon: ShieldAlert,
        title: "此檔案受保護，不提供預覽",
        detail: "依安全政策，這類檔案不會在瀏覽器中顯示，內容未被讀取或傳輸。",
        next: "此處沒有可進行的操作。",
      };
    case "denied_access":
      // Worded so that "missing", "moved" and "outside the workspace" read the
      // same: an answer that told them apart would be a path oracle.
      return {
        ...base,
        icon: FileQuestion,
        title: "無法存取此檔案",
        detail: "檔案可能已移動或刪除，或不在可預覽的範圍內。",
        next: "請重新整理檔案清單後再試。",
        action: { label: "重新整理清單", emit: "refresh-list" },
      };
    case "permission":
      return {
        ...base,
        icon: Lock,
        title: "Node 上沒有讀取權限",
        detail: "執行 daemon 的使用者無法讀取這個檔案。",
        next: "請洽節點擁有者調整檔案權限。",
      };
    case "too_large":
      return {
        ...base,
        icon: HardDrive,
        title: "檔案過大，無法預覽",
        detail: `檔案大小 ${formatBytes(d.size)}，預覽上限 ${formatBytes(d.limit)}。`,
        next: "請在 Node 上用終端機處理此檔案。",
      };
    case "limit":
      return {
        ...base,
        icon: Scaling,
        title: "超過預覽上限",
        detail:
          LIMIT_DETAIL[d.reason ?? ""] ??
          "檔案超過預覽的像素、邊長或複雜度上限。",
        next: "這個上限保護 Node 與瀏覽器不被耗盡資源，無法在此預覽。",
      };
    case "invalid":
      return {
        ...base,
        icon: FileWarning,
        title: "檔案可能已損毀",
        detail: "檔案的表頭或結構檢查未通過，因此沒有送出任何內容。",
        next: "請確認檔案是否完整。",
      };
    case "changed":
      return {
        ...base,
        icon: RefreshCw,
        title: "檔案正在變動",
        detail: "讀取期間檔案被修改；為避免顯示不一致的內容，已停止載入。",
        next: "等檔案寫完後再重試。",
        action: { label: "重試", emit: "retry" },
      };
    case "unsupported":
      return {
        ...base,
        icon: FileType,
        title: "這不是可預覽的圖片或 PDF",
        detail: "依檔案內容判定，它不是 PNG、JPEG、WebP、GIF 或 PDF。",
        next: "可以改用文字預覽開啟。",
        action: { label: "改用文字預覽", emit: "text" },
      };
    case "render_failed":
      return {
        ...base,
        icon: ImageOff,
        title: "此瀏覽器無法顯示這個檔案",
        detail: "瀏覽器解碼或繪製失敗，已清除取得的內容。",
        next: "可以換一個瀏覽器，或在 Node 上用終端機處理。",
      };
    case "unsupported_browser":
      return {
        ...base,
        icon: MonitorX,
        title: "瀏覽器不支援此預覽",
        detail: "這個瀏覽器缺少在頁面中顯示圖片所需的功能。",
        next: "請更新瀏覽器，或改用其他瀏覽器。",
      };
    case "offline":
      return {
        ...base,
        icon: WifiOff,
        title: "Node 離線",
        detail: "Node 目前沒有連線，無法取得檔案。",
        next: "Node 重新連線後再重試。",
        action: { label: "重試", emit: "retry" },
      };
    case "forbidden":
      return {
        ...base,
        icon: Ban,
        title: "沒有權限檢視檔案",
        detail: "你的角色或這個 session 不允許檢視此檔案。",
        next: "如需權限，請洽管理者。",
      };
    case "busy":
      return {
        ...base,
        icon: Hourglass,
        title: "預覽忙碌中",
        detail: "同時進行的預覽太多，Node 或中央暫時無法處理。",
        next: "請稍後再重試。",
        action: { label: "重試", emit: "retry" },
      };
    case "transfer_failed":
      return {
        ...base,
        icon: Unplug,
        title: "傳輸中斷",
        detail: "檔案沒有完整送達；為避免顯示不完整的內容，已全部捨棄。",
        next: "請重試。",
        action: { label: "重試", emit: "retry" },
      };
    case "pdf_password_required":
      // No password field, here or anywhere (OD-8). The bytes that arrived
      // have already been discarded with the document.
      return {
        ...base,
        icon: KeyRound,
        title: "此 PDF 需要密碼才能開啟，預覽不支援",
        detail: "預覽不提供密碼輸入；已取得的內容已清除。",
        next: "請在 Node 上用終端機處理此檔案。",
      };
    case "pdf_too_many_pages":
      return {
        ...base,
        icon: Files,
        title: "PDF 頁數超過預覽上限",
        detail: `這份 PDF 有 ${d.pages ?? "未知"} 頁，預覽上限為 ${d.limit ?? 200} 頁。`,
        next: "頁數在上限內的 PDF 才能在此預覽。",
      };
    case "session_ended":
      // No retry: asking a session that is over only fails again.
      return {
        ...base,
        icon: CircleStop,
        title: "Session 已結束",
        detail: "這個 session 已結束，無法再讀取工作區檔案。",
        next: "回到 session 清單開啟新的 session。",
      };
  }
}

const view = computed<View>(() =>
  props.binary
    ? binaryView(props.binary.state, props.binary.detail)
    : textView(props.denial ?? { code: "FILE_DENIED" }),
);

function textView(d: PreviewDenial): View {
  switch (d.code) {
    case "FILE_TOO_LARGE": {
      // Two ceilings, and they are not the same number. Between them sits a band
      // of files that cannot be shown and can be taken away.
      const downloadable = d.size !== undefined && d.size <= MAX_DOWNLOAD_BYTES;
      return {
        icon: HardDrive,
        title: "檔案過大，超過預覽上限",
        detail: `檔案大小 ${formatBytes(d.size)}，預覽上限 2 MiB。`,
        next: downloadable
          ? "此檔案仍在下載上限（4 MiB）之內，可以直接下載後用本機工具開啟。"
          : "超過下載上限（4 MiB），請在 Node 上以終端機處理此檔案。",
        // The offer has to be withdrawn for the files it would fail on, or the
        // button becomes the thing that teaches users the size limit.
        offerDownload: downloadable,
      };
    }
    case "FILE_BINARY": {
      const meta = `大小 ${formatBytes(d.size)}${
        d.modifiedAt
          ? `，修改時間 ${new Date(d.modifiedAt).toLocaleString()}`
          : ""
      }`;
      // Two different facts arrive under one wire code, and they call for
      // different actions: "this is not text, stop looking" versus "this is
      // text we cannot decode, convert it". Saying "binary" about a Big5 source
      // file is simply wrong, and it was part of what users were reporting.
      if (d.reason === "unsupported_encoding") {
        return {
          icon: FileQuestion,
          title: "無法以 UTF-8 顯示此檔案",
          detail: `檔案看起來是文字，但不是 UTF-8 編碼（例如 Big5、GBK、Shift-JIS 或 UTF-16）。${meta}。`,
          next: "可以下載後用本機工具轉碼，或在 Node 上以 iconv 轉為 UTF-8。",
          offerDownload: true,
        };
      }
      return {
        icon: Ban,
        title: "不支援預覽此檔案",
        detail: `偵測為二進位內容（${d.mime ?? "application/octet-stream"}），${meta}。`,
        // Not previewable is not the same as not obtainable, and this is the pane
        // where that distinction is worth the most: a PNG or a .parquet is a file
        // the user has every reason to want and no reason to want rendered here.
        next: "此處僅顯示檔案資訊，不載入內容；下載可取得完整檔案。",
        offerDownload: true,
      };
    }
    case "FILE_PERMISSION_DENIED":
      return {
        icon: Lock,
        title: "無讀取權限",
        detail: "執行 daemon 的使用者沒有讀取此檔案的權限。",
        next: "請洽 Node 管理者調整檔案權限，或改用其他檔案。",
        offerDownload: false,
      };
    case "FILE_NOT_FOUND":
      return {
        icon: FileQuestion,
        title: "檔案已不存在或無法存取",
        detail: "此路徑目前無法存取。",
        next: "請重新整理檔案樹以取得最新內容。",
        offerDownload: false,
      };
    default:
      return {
        icon: ShieldAlert,
        title: "此檔案為敏感類型，預設不可預覽",
        detail: `分類：${REASONS[d.reason ?? ""] ?? "敏感或不確定的檔案類型"}。內容完全未被讀取或傳輸。`,
        // Deliberately unchanged by download: the node applies the SAME
        // SensitiveClassification on both paths, so this file is refused either
        // way, and offering the button here would be the one place the UI implied
        // otherwise (ADR 0028 §3).
        next: "此為安全政策預設拒絕；下載同樣被拒，必要時請由 Node 管理者於 daemon 設定調整敏感規則。",
        offerDownload: false,
      };
  }
}
</script>

<template>
  <div class="denied" role="status" aria-live="polite">
    <component :is="view.icon" class="glyph" :size="22" aria-hidden="true" />
    <h3>{{ view.title }}</h3>
    <p class="path">{{ relPath }}</p>
    <p class="detail">{{ view.detail }}</p>
    <p class="next">下一步：{{ view.next }}</p>
    <!-- The binary branch: at most one action, and only where it can help. -->
    <div v-if="binary" class="actions" data-binary>
      <button
        v-if="view.action?.emit === 'retry'"
        type="button"
        class="ghost"
        @click="emit('retry')"
      >
        {{ view.action.label }}
      </button>
      <button
        v-else-if="view.action?.emit === 'text'"
        type="button"
        class="ghost"
        @click="emit('text')"
      >
        {{ view.action.label }}
      </button>
      <button
        v-else-if="view.action?.emit === 'refresh-list'"
        type="button"
        class="ghost"
        @click="emit('refresh-list')"
      >
        {{ view.action.label }}
      </button>
    </div>
    <div v-else class="actions">
      <button type="button" class="ghost" @click="emit('refresh')">
        重新檢查
      </button>
      <!-- Offered only where it can actually succeed. The sensitive, permission
           and not-found verdicts set no `offerDownload`, because the node refuses
           those on the download path too (by the same function) and a button that
           reproduces the refusal is worse than no button. -->
      <button
        v-if="canDownload && view.offerDownload"
        type="button"
        class="ghost"
        :disabled="downloading"
        @click="emit('download')"
      >
        {{ downloading ? "下載中…" : "下載檔案" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.denied {
  display: grid;
  justify-items: start;
  gap: 6px;
  padding: 16px;
  height: 100%;
  align-content: center;
  background: var(--terminal-background);
  border-radius: var(--radius-control);
  color: var(--terminal-foreground);
}
.glyph {
  color: var(--status-warning-fg);
}
h3 {
  margin: 0;
  font-size: 13px;
}
.path {
  margin: 0;
  font-family:
    JetBrains Mono,
    ui-monospace,
    monospace;
  font-size: 11px;
  color: var(--text-on-terminal-dim);
  overflow-wrap: anywhere;
}
.detail,
.next {
  margin: 0;
  font-size: 12px;
  color: var(--text-on-terminal);
  max-width: 46ch;
}
.next {
  color: var(--text-on-terminal-dim);
}
.actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.ghost {
  margin-top: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border-on-terminal-control);
  border-radius: var(--radius-control);
  background: var(--surface-on-terminal);
  color: var(--text-on-terminal);
  font-size: 11px;
  font-weight: 600;
}
/* The binary preview is full-screen on a phone, and these are its only
   actions there: the real box reaches the touch floor. */
@media (max-width: 767px) {
  .actions[data-binary] .ghost {
    min-height: var(--density-touch);
    padding: 0 14px;
  }
}
</style>
