<script setup lang="ts">
// The fleet dashboard (P4-08, PRD §10.2, style §10/§23).
//
// The page's whole job is to be **honest about what it knows**, so it is built around
// three refusals:
//
//   * **no automatic polling by default.** A page that refreshes itself looks live even
//     while a block is `stale`, which is exactly the impression the server-side freshness
//     contract exists to prevent. Refresh is a button; a 30 s auto-refresh is an opt-in
//     toggle whose state lives in the store so it survives navigation.
//   * **no skeleton once there is data.** A skeleton means "we are fetching for the first
//     time". Showing one on every refresh would manufacture activity, and showing one
//     when a block is simply empty would suggest data is coming that never will.
//   * **one failing block degrades one card.** The response is still a success; the other
//     cards show real numbers, and the page says once, at the top, that it is incomplete.

import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import { ACTION_AUDIT_VIEW, ACTION_ENROLLMENT_MANAGE } from "../api/dto";
import AppLayout from "../components/layout/AppLayout.vue";
import AsyncState from "../components/common/AsyncState.vue";
import ErrorNotice from "../components/common/ErrorNotice.vue";
import ActivityTimeline from "../components/dashboard/ActivityTimeline.vue";
import HealthCard from "../components/dashboard/HealthCard.vue";
import MetricCard from "../components/dashboard/MetricCard.vue";
import UnhealthyNodeList from "../components/dashboard/UnhealthyNodeList.vue";
import { useAuthStore } from "../stores/auth";
import { AUTO_REFRESH_MS, useDashboardStore } from "../stores/dashboard";

const auth = useAuthStore();
const dashboard = useDashboardStore();
const router = useRouter();

const canManageEnrollment = computed(() =>
  auth.hasPermission(ACTION_ENROLLMENT_MANAGE),
);
const canViewAudit = computed(() => auth.hasPermission(ACTION_AUDIT_VIEW));

// One clock for the whole page, ticked so every FreshnessBadge's relative age advances
// without a dozen independent timers. Ticking the *clock* is not polling the server —
// nothing is refetched, the displayed age simply stops being wrong.
const now = ref(Date.now());
let clock: ReturnType<typeof setInterval> | null = null;

const blocks = computed(() => dashboard.summary?.blocks ?? null);

// `prefers-reduced-motion` disables the refreshing shimmer. Read once rather than
// watched: it is a system preference, and a page that restyles itself mid-session is
// worse than one that needs a reload after the setting changes.
const reducedMotion =
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

onMounted(async () => {
  clock = setInterval(() => {
    now.value = Date.now();
  }, 5000);
  await dashboard.load();
  // Re-arm a preference the user set on a previous visit.
  if (dashboard.autoRefresh) {
    dashboard.setAutoRefresh(true);
  }
});

onUnmounted(() => {
  if (clock !== null) {
    clearInterval(clock);
    clock = null;
  }
  dashboard.detach();
});

function toggleAutoRefresh(event: Event): void {
  dashboard.setAutoRefresh((event.target as HTMLInputElement).checked);
}

function openNode(id: string): void {
  void router.push({ name: "node-detail", params: { id } });
}

// Announced rather than only rendered: a refresh that changes nothing visible, or a
// block that has just gone stale, is otherwise silent for a screen reader.
const announcement = computed(() => {
  if (dashboard.state === "loading") {
    return "正在載入 Dashboard…";
  }
  if (dashboard.state !== "success") {
    return "";
  }
  const parts: string[] = ["Dashboard 已更新"];
  if (dashboard.degradedBlocks.length) {
    parts.push(`${dashboard.degradedBlocks.length} 個區塊無法取得`);
  }
  if (dashboard.staleBlocks.length) {
    parts.push(`${dashboard.staleBlocks.length} 個區塊資料可能過時`);
  }
  return `${parts.join("；")}。`;
});

const sessions = computed(() => blocks.value?.sessions.data ?? null);
const resources = computed(() => blocks.value?.resources.data ?? null);

// Fleet CPU/memory/disk: `null` when nothing reported, never 0. The server distinguishes
// them and so must this — 0% CPU and "no node has reported" are different facts.
function measurement(name: string): number | null {
  const found = resources.value?.measurements[name];
  if (!found || found.nodes === 0 || found.average === null) {
    return null;
  }
  return Math.round(found.average * 10) / 10;
}

function reportingCaption(name: string): string | undefined {
  const found = resources.value?.measurements[name];
  return found && found.nodes > 0 ? `${found.nodes} 個 Node 回報` : undefined;
}
</script>

<template>
  <AppLayout>
    <header class="head">
      <div>
        <h1>Dashboard</h1>
        <p>此控制平面的即時概況。</p>
      </div>
      <div class="head-actions">
        <label class="auto">
          <input
            type="checkbox"
            :checked="dashboard.autoRefresh"
            @change="toggleAutoRefresh"
          />
          <span>每 {{ AUTO_REFRESH_MS / 1000 }} 秒自動更新</span>
        </label>
        <button
          class="ghost"
          type="button"
          :disabled="dashboard.state === 'loading'"
          @click="dashboard.load()"
        >
          {{ dashboard.refreshing ? "更新中…" : "重新整理" }}
        </button>
      </div>
    </header>

    <p class="sr-only" role="status" aria-live="polite">{{ announcement }}</p>

    <AsyncState v-if="dashboard.state === 'loading'" state="loading">
      正在載入 Dashboard…
    </AsyncState>
    <AsyncState v-else-if="dashboard.state === 'forbidden'" state="forbidden">
      你沒有檢視 Dashboard 的權限。
    </AsyncState>
    <ErrorNotice
      v-else-if="dashboard.state === 'error'"
      :error="dashboard.error"
      @retry="dashboard.load()"
    />

    <template v-else-if="blocks">
      <!-- A refresh that failed keeps the numbers on screen and says so, rather than
           discarding readable data because one poll did not land. -->
      <AsyncState v-if="dashboard.error" state="stale" class="notice">
        最近一次更新失敗，以下為上次成功取得的資料。
      </AsyncState>

      <AsyncState
        v-if="dashboard.degradedBlocks.length"
        state="partial"
        class="notice"
      >
        有
        {{ dashboard.degradedBlocks.length }}
        個區塊暫時無法取得；其餘數字仍為真實資料。
      </AsyncState>

      <AsyncState
        v-if="dashboard.isEmptyDeployment"
        state="empty"
        class="notice"
      >
        尚未安裝任何 Node。
        <RouterLink v-if="canManageEnrollment" :to="{ name: 'enrollment' }">
          建立安裝 Token 以加入第一個 Node
        </RouterLink>
        <span v-else>請聯繫 Admin 建立安裝 Token。</span>
      </AsyncState>
      <AsyncState
        v-else-if="dashboard.isFleetOffline"
        state="offline"
        class="notice"
      >
        所有 Node 都不在線。請依 heartbeat-loss runbook 檢查網路與各節點的
        agentd 服務。
      </AsyncState>

      <div class="grid" :data-reduced-motion="reducedMotion">
        <MetricCard
          title="線上 Node"
          icon="●"
          :value="blocks.nodes.data?.online ?? null"
          :status="blocks.nodes.status"
          :generated-at="blocks.nodes.generated_at"
          :now="now"
          :error-code="blocks.nodes.error_code"
          :caption="
            blocks.nodes.data
              ? `共 ${blocks.nodes.data.total} 個 Node`
              : undefined
          "
          tone="good"
          @retry="dashboard.load()"
        />
        <MetricCard
          title="離線 Node"
          icon="○"
          :value="blocks.nodes.data?.offline ?? null"
          :status="blocks.nodes.status"
          :generated-at="blocks.nodes.generated_at"
          :now="now"
          :error-code="blocks.nodes.error_code"
          :caption="
            blocks.nodes.data
              ? `降級 ${blocks.nodes.data.degraded}・停用 ${blocks.nodes.data.disabled}`
              : undefined
          "
          :tone="(blocks.nodes.data?.offline ?? 0) > 0 ? 'warn' : 'neutral'"
          @retry="dashboard.load()"
        />
        <MetricCard
          title="執行中 Session"
          icon="▷"
          :value="sessions?.total_active ?? null"
          :status="blocks.sessions.status"
          :generated-at="blocks.sessions.generated_at"
          :now="now"
          :error-code="blocks.sessions.error_code"
          :caption="
            sessions
              ? `啟動中 ${sessions.starting}・已斷線 ${sessions.disconnected}`
              : undefined
          "
          @retry="dashboard.load()"
        />
        <MetricCard
          title="Claude Session"
          icon="◆"
          :value="sessions ? (sessions.per_runtime.claude ?? 0) : null"
          :status="blocks.sessions.status"
          :generated-at="blocks.sessions.generated_at"
          :now="now"
          :error-code="blocks.sessions.error_code"
          @retry="dashboard.load()"
        />
        <MetricCard
          title="Codex Session"
          icon="◇"
          :value="sessions ? (sessions.per_runtime.codex ?? 0) : null"
          :status="blocks.sessions.status"
          :generated-at="blocks.sessions.generated_at"
          :now="now"
          :error-code="blocks.sessions.error_code"
          @retry="dashboard.load()"
        />
        <MetricCard
          title="CPU（fleet 平均）"
          icon="▮"
          :value="measurement('cpu_usage')"
          unit="%"
          :status="blocks.resources.status"
          :generated-at="blocks.resources.generated_at"
          :now="now"
          :error-code="blocks.resources.error_code"
          :caption="reportingCaption('cpu_usage')"
          @retry="dashboard.load()"
        />
        <MetricCard
          title="記憶體（fleet 平均）"
          icon="▩"
          :value="measurement('memory_usage')"
          unit="%"
          :status="blocks.resources.status"
          :generated-at="blocks.resources.generated_at"
          :now="now"
          :error-code="blocks.resources.error_code"
          :caption="reportingCaption('memory_usage')"
          @retry="dashboard.load()"
        />
        <MetricCard
          title="磁碟（fleet 平均）"
          icon="▤"
          :value="measurement('disk_usage')"
          unit="%"
          :status="blocks.resources.status"
          :generated-at="blocks.resources.generated_at"
          :now="now"
          :error-code="blocks.resources.error_code"
          :caption="reportingCaption('disk_usage')"
          @retry="dashboard.load()"
        />
      </div>

      <div class="panels">
        <HealthCard
          :runtimes="blocks.runtimes.data"
          :status="blocks.runtimes.status"
          :generated-at="blocks.runtimes.generated_at"
          :now="now"
          :error-code="blocks.runtimes.error_code"
          @retry="dashboard.load()"
        />
        <UnhealthyNodeList
          :items="blocks.unhealthy_nodes.data?.items ?? []"
          :total="blocks.unhealthy_nodes.data?.total ?? 0"
          :status="blocks.unhealthy_nodes.status"
          :generated-at="blocks.unhealthy_nodes.generated_at"
          :now="now"
          :error-code="blocks.unhealthy_nodes.error_code"
          @retry="dashboard.load()"
          @open="openNode"
        />
        <ActivityTimeline
          :activity="blocks.recent_activity.data"
          :status="blocks.recent_activity.status"
          :generated-at="blocks.recent_activity.generated_at"
          :now="now"
          :error-code="blocks.recent_activity.error_code"
          :can-view-audit="canViewAudit"
          @retry="dashboard.load()"
        />
      </div>
    </template>
  </AppLayout>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
.head h1 {
  margin: 0;
  font-size: 24px;
}
.head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.auto {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}
.ghost {
  padding: 8px 14px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--surface-default);
  color: var(--text-secondary);
  font-weight: 600;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.notice {
  margin-bottom: 14px;
}
.grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  margin-bottom: 18px;
}
.panels {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
</style>
