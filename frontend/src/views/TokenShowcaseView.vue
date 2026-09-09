<script setup lang="ts">
// The acceptance panel. Dev-only (`import.meta.env.DEV` in the router), so it
// never reaches a production bundle.
//
// It used to show three components. It now shows every shared component in
// every state it has, because that is what the evidence pack screenshots: one
// page per theme rather than a hunt through eleven views for a disabled button
// and a warning badge. If a state cannot be reached here, it cannot be
// photographed, and "we checked" becomes the only evidence available.
//
// The contrast table is rendered from the same PAIRS list the unit test
// asserts, with its measured values. A page that says "all pass" is a rubber
// stamp; a page that prints 4.72:1 next to the two colours can be disagreed
// with.

import { computed, ref } from "vue";
import { AlertTriangle, Copy, Server, Trash2 } from "lucide-vue-next";

import AppLayout from "../components/layout/AppLayout.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
import ConfirmDialog from "../components/common/ConfirmDialog.vue";
import UiActionMenu from "../components/ui/UiActionMenu.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiDataTable from "../components/ui/UiDataTable.vue";
import UiDialog from "../components/ui/UiDialog.vue";
import UiEmptyState from "../components/ui/UiEmptyState.vue";
import UiField from "../components/ui/UiField.vue";
import UiIconButton from "../components/ui/UiIconButton.vue";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import UiLoadingState from "../components/ui/UiLoadingState.vue";
import UiToolbar from "../components/ui/UiToolbar.vue";
import ThemeMenu from "../components/layout/ThemeMenu.vue";
import { PAIRS, contrastRatio } from "../theme/contrast";
import { THEMES, type ColorToken } from "../theme/themes";
import { usePreferencesStore } from "../stores/preferences";
import { useToast } from "../composables/useToast";

const preferences = usePreferencesStore();
const toast = useToast();

const dialogOpen = ref(false);
const confirmOpen = ref(false);
const fieldValue = ref("");

// Measured against the theme actually on screen, so the numbers on the page and
// the colours on the page cannot disagree.
const rows = computed(() =>
  PAIRS.map((pair) => {
    const theme = THEMES[preferences.theme];
    const fg = theme[pair.fg as ColorToken];
    const bg = theme[pair.bg as ColorToken];
    const ratio = contrastRatio(fg, bg);
    return { ...pair, fg, bg, ratio, pass: ratio >= pair.target };
  }),
);
const failures = computed(() => rows.value.filter((row) => !row.pass).length);

// A long name and a deep path, the fixtures the acceptance matrix's "long text"
// cell uses. Kept here so the screenshot for that cell is reproducible rather
// than typed by hand each time.
const LONG_NAME =
  "重構 API 客戶端與錯誤處理，並補上 reconnect 的回歸測試 🎨 refactor-api-client";
const LONG_PATH =
  "/home/deploy/workspaces/relvo/2026/q3/cliora-frontend-visual-refresh";
</script>

<template>
  <!-- Inside the real shell, so a screenshot of this page shows the components
       against the same surfaces they will actually sit on. A showcase floating
       on a bare body would photograph the wrong background. -->
  <AppLayout>
    <section class="showcase">
      <header>
        <span class="eyebrow">Foundation</span>
        <h1>元件與 token 驗收面板</h1>
        <p>
          每個共用元件的每一種狀態，兩款主題各一次。狀態不靠顏色單獨表達，
          每個控制項都有看得見的焦點指示。
        </p>
        <ThemeMenu />
      </header>

      <h2>Buttons</h2>
      <div class="row">
        <UiButton variant="primary">主要動作</UiButton>
        <UiButton variant="secondary">次要動作</UiButton>
        <UiButton variant="quiet">低強度</UiButton>
        <UiButton variant="danger">危險動作</UiButton>
        <UiButton variant="primary" busy>進行中</UiButton>
        <!-- A disabled button keeps a legible label and says why. Opacity would
           make the reason unreadable along with the label. -->
        <UiButton disabled disabled-reason="需要 session.terminate 權限">
          已停用
        </UiButton>
      </div>

      <h2>Icon buttons</h2>
      <div class="row">
        <UiIconButton label="複製路徑"><Copy /></UiIconButton>
        <UiIconButton variant="secondary" label="檢視節點"
          ><Server
        /></UiIconButton>
        <UiIconButton variant="danger" label="刪除"><Trash2 /></UiIconButton>
        <UiIconButton label="已選取" pressed><AlertTriangle /></UiIconButton>
        <UiIconButton label="無法使用" disabled disabled-reason="節點離線">
          <Server />
        </UiIconButton>
        <UiActionMenu>
          <template #default="{ close }">
            <button type="button" @click="close()">一般項目</button>
            <button type="button" data-danger @click="close()">
              危險項目…
            </button>
            <button type="button" disabled>已停用項目</button>
          </template>
        </UiActionMenu>
      </div>

      <h2>Status badges</h2>
      <p class="note">
        五個語意 × 三個來源。顏色只有五種，文字不共用——
        <code>exited</code> 在 Session 與連線兩種語彙下是不同的事實。
      </p>
      <div class="row">
        <StatusBadge status="online" kind="node" />
        <StatusBadge status="degraded" kind="node" />
        <StatusBadge status="offline" kind="node" />
        <StatusBadge status="error" kind="node" />
      </div>
      <div class="row">
        <StatusBadge status="connected" kind="connection" />
        <StatusBadge status="reconnecting" kind="connection" />
        <StatusBadge status="disconnected" kind="connection" />
        <StatusBadge status="gap" kind="connection" />
        <StatusBadge status="exited" kind="connection" />
      </div>
      <div class="row">
        <StatusBadge status="running" kind="session" />
        <StatusBadge status="exited" kind="session" />
        <StatusBadge status="failed" kind="session" />
        <StatusBadge status="active" kind="token" />
        <StatusBadge status="available" kind="runtime" />
      </div>

      <h2>Notices</h2>
      <div class="stack">
        <UiInlineNotice tone="info" title="資訊" message="這是一則說明。" />
        <UiInlineNotice
          tone="warning"
          title="來源目前離線"
          message="以下為最後一次 heartbeat 的資料。"
        />
        <UiInlineNotice tone="error" title="上傳失敗">
          <code>測試-檔案-名稱-很長-的-那-一-個-🎨.tsx</code> —
          目標目錄已存在同名檔案。
          <template #actions>
            <UiButton variant="secondary">改名重試</UiButton>
          </template>
        </UiInlineNotice>
        <UiInlineNotice
          tone="stale"
          title="資料可能不是最新"
          message="最近一次更新失敗，畫面上是上次成功取得的資料。"
        />
      </div>

      <h2>Empty states</h2>
      <p class="note">
        空清單與篩選無結果是兩段不同文案，因為要做的事不同：一個是建立第一筆，
        一個是清掉篩選。
      </p>
      <div class="pair">
        <div class="card">
          <UiEmptyState
            variant="empty"
            title="尚未建立 Session"
            detail="從「建立 Session」開始一段新的工作。"
          >
            <template #action
              ><UiButton variant="primary">建立 Session</UiButton></template
            >
          </UiEmptyState>
        </div>
        <div class="card">
          <UiEmptyState
            variant="no-results"
            title="沒有符合條件的項目"
            detail="調整搜尋字串，或清除 Runtime 篩選。"
          >
            <template #action
              ><UiButton variant="secondary">清除篩選</UiButton></template
            >
          </UiEmptyState>
        </div>
      </div>

      <h2>Loading</h2>
      <div class="card"><UiLoadingState :lines="3" label="正在載入清單" /></div>

      <h2>Fields</h2>
      <div class="pair">
        <UiField label="Session 名稱" required hint="最多 60 個字元">
          <template #default="{ id, describedBy, required }">
            <input
              :id="id"
              v-model="fieldValue"
              :aria-describedby="describedBy"
              :required="required"
              placeholder="例如：Review authentication flow"
            />
          </template>
        </UiField>
        <UiField
          label="Workspace"
          error="這個路徑不在允許的 Workspace Root 範圍內。"
        >
          <template #default="{ id, describedBy, invalid }">
            <input
              :id="id"
              value="/etc"
              :aria-describedby="describedBy"
              :aria-invalid="invalid"
            />
          </template>
        </UiField>
        <UiField label="Node" disabled-reason="沒有線上的節點">
          <template #default="{ id }"
            ><select :id="id" disabled>
              <option>—</option>
            </select></template
          >
        </UiField>
      </div>

      <h2>Toolbar</h2>
      <UiToolbar label="示範工具列">
        <UiIconButton label="重新整理"><Server /></UiIconButton>
        <UiIconButton label="複製"><Copy /></UiIconButton>
        <template #end><UiButton variant="quiet">全部展開</UiButton></template>
      </UiToolbar>

      <h2>Data table</h2>
      <UiDataTable
        label="示範表格"
        :columns="['SESSION / WORKSPACE', 'NODE', 'RUNTIME', '狀態']"
      >
        <tr>
          <td>
            <UiButton variant="quiet">{{ LONG_NAME }}</UiButton>
            <small>{{ LONG_PATH }}</small>
          </td>
          <td>build-node-ap-northeast-1-spot-0007</td>
          <td>Claude</td>
          <td><StatusBadge status="running" kind="session" /></td>
        </tr>
        <tr aria-selected="true">
          <td>
            <UiButton variant="quiet">選取中的列</UiButton>
            <small>/workspace/cliora</small>
          </td>
          <td>dev-node-01</td>
          <td>Codex</td>
          <td><StatusBadge status="exited" kind="session" /></td>
        </tr>
      </UiDataTable>

      <h2>Overlays</h2>
      <div class="row">
        <UiButton variant="secondary" @click="dialogOpen = true"
          >開啟 Dialog</UiButton
        >
        <UiButton variant="danger" @click="confirmOpen = true"
          >危險確認</UiButton
        >
        <UiButton
          variant="secondary"
          @click="toast.success('已建立示範 Session')"
        >
          成功 Toast
        </UiButton>
        <UiButton variant="secondary" @click="toast.info('已重新整理')">
          資訊 Toast
        </UiButton>
      </div>
      <p class="note">
        Toast 的型別沒有
        <code>error</code> 成員。會自己消失的錯誤訊息等於沒有錯誤訊息，
        所以失敗一律留在相關區域。
      </p>

      <UiDialog
        :open="dialogOpen"
        title="示範 Dialog"
        @cancel="dialogOpen = false"
      >
        <p>焦點被關在 Dialog 內，Esc 可關閉，關閉後焦點回到觸發它的按鈕。</p>
        <template #actions>
          <UiButton variant="secondary" @click="dialogOpen = false"
            >取消</UiButton
          >
          <UiButton variant="primary" @click="dialogOpen = false"
            >確認</UiButton
          >
        </template>
      </UiDialog>

      <ConfirmDialog
        :open="confirmOpen"
        danger
        title="終止此 Session？"
        confirm-label="確認終止"
        @cancel="confirmOpen = false"
        @confirm="confirmOpen = false"
      >
        <p>
          將終止 <code>{{ LONG_NAME }}</code
          >，此 Node 上的 CLI 程序會被停止。
        </p>
      </ConfirmDialog>

      <h2>Contrast, measured</h2>
      <p class="note">
        以下是元件契約產生的配對清單，對目前主題（<code>{{
          preferences.theme
        }}</code
        >）的實測值。不通過：<strong>{{ failures }}</strong> 組。 同一份清單由
        <code>theme.contrast.test.ts</code> 逐組斷言。
      </p>
      <UiDataTable
        label="對比實測"
        :columns="['配對', '元件', '值', '實測', '目標', '判定']"
      >
        <tr v-for="row in rows" :key="`${row.fg}/${row.bg}/${row.what}`">
          <td>
            {{ row.what }}
            <small>{{ row.fg }} / {{ row.bg }}</small>
          </td>
          <td class="dim">{{ row.component }}</td>
          <td>
            <span class="swatch" :style="{ background: row.bg, color: row.fg }"
              >Aa</span
            >
          </td>
          <td class="num">{{ row.ratio.toFixed(2) }}:1</td>
          <td class="num dim">{{ row.target }}</td>
          <td>
            <StatusBadge :status="row.pass ? 'online' : 'error'" kind="node" />
          </td>
        </tr>
      </UiDataTable>
    </section>
  </AppLayout>
</template>

<style scoped>
.showcase {
  display: grid;
  gap: 12px;
  padding: 8px 0 64px;
  max-width: 1100px;
}
header {
  display: grid;
  gap: 8px;
  justify-items: start;
  margin-bottom: 12px;
}
.eyebrow {
  color: var(--accent-strong);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: -0.02em;
}
h2 {
  margin: 24px 0 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-secondary);
}
p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.note {
  font-size: 12px;
  max-width: 80ch;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.stack {
  display: grid;
  gap: 8px;
}
.pair {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
  align-items: start;
}
.card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
  padding: 12px;
}
.dim {
  color: var(--text-secondary);
  font-size: 11px;
}
.num {
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}
.swatch {
  display: inline-grid;
  place-items: center;
  width: 42px;
  height: 26px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  font-size: 12px;
  font-weight: 600;
}
code {
  font-family: var(--font-mono);
  font-size: 11px;
}
</style>
