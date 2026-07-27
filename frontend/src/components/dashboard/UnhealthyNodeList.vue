<script setup lang="ts">
// The unhealthy-node list, with a reason per node (P4-08, PRD §10.2).
//
// Two things it must get right:
//
//   * **say why.** A list of node names tells an operator nothing they did not already
//     suspect. Each row states its reason codes in words, and a node can have several.
//   * **be honest about truncation.** The server bounds the list; when it does, this says
//     "showing 10 of 37" rather than implying the list is complete.

import type {
  DashboardBlockStatus,
  UnhealthyNode,
  UnhealthyReason,
} from "../../api/dto";
import { formatInstant } from "../../utils/time";
import FreshnessBadge from "./FreshnessBadge.vue";

defineProps<{
  items: UnhealthyNode[];
  total: number;
  status: DashboardBlockStatus;
  generatedAt: string;
  now: number;
  errorCode?: string | null;
}>();

const emit = defineEmits<{ retry: []; open: [id: string] }>();

const REASONS: Record<UnhealthyReason, string> = {
  offline_but_enabled: "已啟用但沒有連線",
  heartbeat_degraded: "心跳延遲（降級）",
  no_runtime_available: "沒有任何可用的 runtime",
  recent_session_failure: "最近有 Session 啟動失敗",
};

function reasonText(reason: UnhealthyReason): string {
  return REASONS[reason] ?? reason;
}

// Keyboard: the node names are real buttons rather than clickable divs, so Enter and
// Space work without this component adding key handlers of its own.
function open(id: string): void {
  emit("open", id);
}
</script>

<template>
  <section class="panel" :data-status="status">
    <header>
      <h3>異常 Node</h3>
      <FreshnessBadge :status="status" :generated-at="generatedAt" :now="now" />
    </header>

    <template v-if="status === 'degraded'">
      <p class="unavailable">暫時無法取得</p>
      <p class="reason">
        <code v-if="errorCode">{{ errorCode }}</code>
        <button type="button" class="retry" @click="emit('retry')">重試</button>
      </p>
    </template>
    <p v-else-if="items.length === 0" class="ok">目前沒有異常的 Node。</p>
    <template v-else>
      <ul>
        <li v-for="node in items" :key="node.id">
          <button type="button" class="name" @click="open(node.id)">
            {{ node.name }}
          </button>
          <ul class="reasons">
            <li v-for="reason in node.reasons" :key="reason">
              {{ reasonText(reason) }}
            </li>
          </ul>
          <time
            v-if="node.last_seen_at"
            :datetime="node.last_seen_at"
            :title="node.last_seen_at"
          >
            最後在線 {{ formatInstant(node.last_seen_at) }}
          </time>
          <span v-else class="never">從未上線</span>
        </li>
      </ul>
      <!-- Never implies the list is everything. -->
      <p v-if="total > items.length" class="truncated">
        顯示 {{ items.length }} 筆，共 {{ total }} 筆異常。
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
li + li {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-default);
}
.reasons li,
.reasons li + li {
  margin: 2px 0 0;
  padding: 0;
  border: 0;
  color: var(--status-busy);
  font-size: 12px;
}
.name {
  padding: 0;
  border: 0;
  background: none;
  color: var(--action-primary);
  font-weight: 600;
  font-size: 13px;
}
time,
.never {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 11px;
}
.ok,
.truncated,
.reason,
.unavailable {
  margin: 0;
  font-size: 12px;
}
.ok,
.truncated {
  color: var(--text-muted);
}
.truncated {
  margin-top: 10px;
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
