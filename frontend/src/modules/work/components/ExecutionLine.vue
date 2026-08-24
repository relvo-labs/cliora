<script setup lang="ts">
/**
 * "What is the agent doing", in one line (PX-18, plan/26/06 §3.2).
 *
 * Words plus a shape, never colour alone (research/style.md §22). The elapsed time is
 * approximate on purpose — "12m" is what a person needs from a board, and the exact
 * timestamp is in the Drawer.
 */
import { computed } from "vue";

const props = defineProps<{
  status: string;
  runnerName: string | null;
  startedAt: string | null;
}>();

const LABELS: Record<string, string> = {
  not_queued: "未派工",
  queued: "排隊中",
  claimed: "已認領",
  running: "執行中",
  waiting_for_input: "等待回覆",
  succeeded: "已完成",
  failed: "失敗",
  cancelled: "已取消",
  lost: "失聯",
};

const label = computed(() => LABELS[props.status] ?? props.status);
const elapsed = computed(() => {
  if (!props.startedAt) return null;
  const minutes = Math.floor(
    (Date.now() - Date.parse(props.startedAt)) / 60000,
  );
  if (Number.isNaN(minutes) || minutes < 0) return null;
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
});
const active = computed(() => ["running", "claimed"].includes(props.status));
</script>

<template>
  <p class="execution" :data-status="status">
    <span v-if="active" class="pulse" aria-hidden="true"></span>
    <span v-if="runnerName" class="runner">{{ runnerName }}</span>
    <span class="status">{{ label }}</span>
    <span v-if="elapsed" class="elapsed">{{ elapsed }}</span>
  </p>
</template>

<style scoped>
.execution {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: var(--space-2) 0 0;
  padding-top: var(--space-2);
  border-top: 1px solid var(--border-default);
  color: var(--text-secondary);
  font-size: var(--font-xs);
}
.runner {
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.elapsed {
  margin-left: auto;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.pulse {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--run-running);
  animation: execution-pulse 1.35s ease-in-out infinite;
}
.execution[data-status="waiting_for_input"] .status {
  color: var(--attention-human);
  font-weight: 600;
}
.execution[data-status="failed"] .status,
.execution[data-status="lost"] .status {
  color: var(--attention-failed);
  font-weight: 600;
}
@keyframes execution-pulse {
  50% {
    opacity: 0.3;
    transform: scale(0.72);
  }
}
@media (prefers-reduced-motion: reduce) {
  .pulse {
    animation: none;
  }
}
</style>
