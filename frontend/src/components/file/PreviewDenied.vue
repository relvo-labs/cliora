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

const props = defineProps<{ denial: PreviewDenial; relPath: string }>();
const emit = defineEmits<{ refresh: [] }>();

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
    case "FILE_TOO_LARGE":
      return {
        icon: HardDrive,
        title: "檔案過大，超過預覽上限",
        detail: `檔案大小 ${formatBytes(d.size)}，預覽上限 2 MiB。`,
        next: "請在 Node 上以終端機檢視此檔案；MVP 不提供完整載入或下載。",
      };
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
          next: "請在 Node 上以 iconv 轉為 UTF-8，或直接以終端機檢視。",
        };
      }
      return {
        icon: Ban,
        title: "不支援預覽此檔案",
        detail: `偵測為二進位內容（${d.mime ?? "application/octet-stream"}），${meta}。`,
        next: "僅顯示檔案資訊，不載入內容。",
      };
    }
    case "FILE_PERMISSION_DENIED":
      return {
        icon: Lock,
        title: "無讀取權限",
        detail: "執行 daemon 的使用者沒有讀取此檔案的權限。",
        next: "請洽 Node 管理者調整檔案權限，或改用其他檔案。",
      };
    case "FILE_NOT_FOUND":
      return {
        icon: FileQuestion,
        title: "檔案已不存在或無法存取",
        detail: "此路徑目前無法存取。",
        next: "請重新整理檔案樹以取得最新內容。",
      };
    default:
      return {
        icon: ShieldAlert,
        title: "此檔案為敏感類型，預設不可預覽",
        detail: `分類：${REASONS[d.reason ?? ""] ?? "敏感或不確定的檔案類型"}。內容完全未被讀取或傳輸。`,
        next: "此為安全政策預設拒絕；必要時請由 Node 管理者於 daemon 設定調整敏感規則。",
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
    <button type="button" class="ghost" @click="emit('refresh')">
      重新檢查
    </button>
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
