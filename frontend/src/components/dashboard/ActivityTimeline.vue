<script setup lang="ts">
// Recent activity: the newest audit entries, safe fields only (P4-08, style §23).
//
// Actor identity is present only for viewers holding `audit.view` — the server strips it
// otherwise and sets `actors_hidden`. This component renders that difference **visibly**
// rather than silently: a Developer seeing a column of dashes with no explanation would
// reasonably conclude the events had no actor, which is not what happened.

import type { DashboardActivity, DashboardBlockStatus } from "../../api/dto";
import { actionLabel } from "../../utils/auditActions";
import { formatInstant } from "../../utils/time";
import FreshnessBadge from "./FreshnessBadge.vue";

defineProps<{
  activity: DashboardActivity | null;
  status: DashboardBlockStatus;
  generatedAt: string;
  now: number;
  errorCode?: string | null;
  // Whether to offer the "see the full audit trail" link, which only Admins can use.
  canViewAudit: boolean;
}>();

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <section class="panel" :data-status="status">
    <header>
      <h3>最近活動</h3>
      <FreshnessBadge :status="status" :generated-at="generatedAt" :now="now" />
    </header>

    <template v-if="status === 'degraded' || activity === null">
      <p class="unavailable">暫時無法取得</p>
      <p class="reason">
        <code v-if="errorCode">{{ errorCode }}</code>
        <button type="button" class="retry" @click="emit('retry')">重試</button>
      </p>
    </template>
    <p v-else-if="activity.items.length === 0" class="empty">
      目前沒有活動紀錄。
    </p>
    <template v-else>
      <!-- Explained once, above the list, rather than leaving a column of dashes to be
           misread as "these events had no actor". -->
      <p v-if="activity.actors_hidden" class="hidden-note">
        只有 Admin 能看到執行者；以下僅顯示動作與時間。
      </p>
      <ol>
        <li v-for="item in activity.items" :key="item.id">
          <time :datetime="item.created_at" :title="item.created_at">
            {{ formatInstant(item.created_at) }}
          </time>
          <span class="action">{{ actionLabel(item.action) }}</span>
          <span v-if="item.actor_name" class="actor">{{
            item.actor_name
          }}</span>
          <span v-if="item.node_name" class="node">{{ item.node_name }}</span>
        </li>
      </ol>
      <RouterLink v-if="canViewAudit" :to="{ name: 'audit' }" class="more">
        查看完整 Audit Log
      </RouterLink>
    </template>
  </section>
</template>

<style scoped>
.panel {
  padding: 16px 18px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
}
.panel[data-status="degraded"] {
  border-color: var(--danger-bg);
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
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
}
ol {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 320px;
  overflow-y: auto;
}
li {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: baseline;
  gap: 4px 10px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
}
li:last-child {
  border-bottom: 0;
}
time {
  color: var(--text-secondary);
  font-size: 11px;
  white-space: nowrap;
}
.action {
  font-weight: 600;
}
.actor,
.node {
  color: var(--text-secondary);
  font-size: 11px;
}
.empty,
.hidden-note,
.unavailable,
.reason {
  margin: 0;
  font-size: 12px;
}
.empty,
.hidden-note {
  color: var(--text-secondary);
}
.hidden-note {
  margin-bottom: 8px;
  font-size: 11px;
}
.unavailable {
  font-weight: 600;
  color: var(--status-error-fg);
}
.reason {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 11px;
}
.retry,
.more {
  padding: 0;
  border: 0;
  background: none;
  color: var(--accent-strong);
  font-weight: 600;
  font-size: 11px;
}
.more {
  display: inline-block;
  margin-top: 10px;
  text-decoration: none;
}
</style>
