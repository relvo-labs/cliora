<script setup lang="ts">
// "Cannot preview" pane. Every denial states what happened, why, and what the
// user can do next — in text, not colour alone. It never renders a content
// fragment, a MIME-typed body, or a server absolute path (SEC-004).

import {
  Ban,
  FileQuestion,
  HardDrive,
  Lock,
  ShieldAlert,
} from "lucide-vue-next";
import { computed } from "vue";

import type { PreviewDenial } from "../../composables/useMonacoModel";

const props = defineProps<{
  denial: PreviewDenial;
  relPath: string;
  // Whether download is available at all here (permission AND the node's own
  // report, resolved upstairs). This pane is the most useful place it can appear:
  // a binary file is precisely the case where "show it" was never the question.
  canDownload?: boolean;
  downloading?: boolean;
}>();
const emit = defineEmits<{ refresh: []; download: [] }>();

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

const view = computed(() => {
  const d = props.denial;
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
});
</script>

<template>
  <div class="denied" role="status" aria-live="polite">
    <component :is="view.icon" class="glyph" :size="22" aria-hidden="true" />
    <h3>{{ view.title }}</h3>
    <p class="path">{{ relPath }}</p>
    <p class="detail">{{ view.detail }}</p>
    <p class="next">下一步：{{ view.next }}</p>
    <div class="actions">
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
</style>
