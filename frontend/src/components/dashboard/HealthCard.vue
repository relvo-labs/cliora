<script setup lang="ts">
// Per-runtime availability across the fleet (style §23 Health Card, PRD §10.2).
//
// The three counts are kept separate on purpose. `unknown` — nodes that have never
// reported this runtime — is not folded into `unavailable`, because silence is not a
// negative: a freshly enrolled fleet would otherwise look entirely broken. The wording
// says which is which rather than leaving a reader to guess from the numbers.

import type { DashboardBlockStatus, DashboardRuntimes } from "../../api/dto";
import FreshnessBadge from "./FreshnessBadge.vue";

defineProps<{
  runtimes: DashboardRuntimes | null;
  status: DashboardBlockStatus;
  generatedAt: string;
  now: number;
  errorCode?: string | null;
}>();

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <section class="panel" :data-status="status">
    <header>
      <h3>Runtime 可用性</h3>
      <FreshnessBadge :status="status" :generated-at="generatedAt" :now="now" />
    </header>

    <template v-if="status === 'degraded' || runtimes === null">
      <p class="unavailable">暫時無法取得</p>
      <p class="reason">
        <code v-if="errorCode">{{ errorCode }}</code>
        <button type="button" class="retry" @click="emit('retry')">重試</button>
      </p>
    </template>
    <p v-else-if="runtimes.eligible_nodes === 0" class="empty">
      尚無啟用中的 Node。
    </p>
    <template v-else>
      <ul>
        <li v-for="(counts, runtime) in runtimes.runtimes" :key="runtime">
          <span class="runtime">{{ runtime }}</span>
          <span class="counts">
            <!-- The word accompanies every number, so meaning never depends on
                 position or colour alone. -->
            <b class="good">{{ counts.available }}</b> 可用
            <b class="bad">{{ counts.unavailable }}</b> 不可用
            <b class="unknown">{{ counts.unknown }}</b> 未回報
          </span>
        </li>
      </ul>
      <p v-if="status === 'stale'" class="stale-note">
        偵測結果可能不是最新（部分 Node 已久未回報）。
      </p>
    </template>
  </section>
</template>

<style scoped>
.panel {
  padding: 16px 18px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
.panel[data-status="degraded"] {
  border-color: var(--border-danger);
}
.panel[data-status="stale"] {
  border-color: var(--status-busy);
}
header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
h3 {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}
ul {
  margin: 0;
  padding: 0;
  list-style: none;
}
li {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-default);
}
li:last-child {
  border-bottom: 0;
}
.runtime {
  font-weight: 600;
  font-size: 13px;
  text-transform: capitalize;
}
.counts {
  color: var(--text-muted);
  font-size: 11px;
}
.counts b {
  margin-left: 8px;
  font-variant-numeric: tabular-nums;
}
.good {
  color: var(--status-online);
}
.bad {
  color: var(--status-error);
}
.unknown {
  color: var(--status-offline);
}
.empty,
.stale-note,
.unavailable,
.reason {
  margin: 0;
  font-size: 12px;
}
.empty {
  color: var(--text-muted);
}
.stale-note {
  margin-top: 8px;
  color: var(--status-busy);
  font-size: 11px;
}
.unavailable {
  font-weight: 600;
  color: var(--status-error);
}
.reason {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 11px;
}
.retry {
  padding: 0;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
  font-size: 11px;
}
</style>
