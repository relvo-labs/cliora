<script setup lang="ts">
// How old a block's data is, and whether it can be trusted (P4-08).
//
// This is the visible half of the server's freshness contract. Two rules it must not
// break:
//
//   * **`stale` still shows the numbers.** Hiding them would be a different lie — the
//     data is real, it is just older than the contract lets it pass as current. So the
//     badge says so in words, not only in colour (WCAG 1.4.1).
//   * **the age comes from the server's `generated_at`**, which is when the data was
//     *fetched*. On a cache hit that is deliberately several seconds ago, and the badge
//     showing "8 seconds ago" rather than "just now" is the contract working.

import { computed } from "vue";

import type { DashboardBlockStatus } from "../../api/dto";
import { formatInstant, localTimeZone } from "../../utils/time";

const props = defineProps<{
  status: DashboardBlockStatus;
  generatedAt: string;
  // Re-rendered when the parent's clock ticks, so the relative age advances without
  // this component owning a timer of its own (one timer per card would be a dozen).
  now: number;
}>();

const ageSeconds = computed(() => {
  const fetched = new Date(props.generatedAt).getTime();
  if (Number.isNaN(fetched)) {
    return null;
  }
  return Math.max(0, Math.round((props.now - fetched) / 1000));
});

// Deliberately coarse. A second-by-second counter reads as a live feed, which is the
// impression this component exists to avoid creating.
const relative = computed(() => {
  const age = ageSeconds.value;
  if (age === null) {
    return "時間不明";
  }
  if (age < 10) {
    return "剛剛";
  }
  if (age < 60) {
    return `${age} 秒前`;
  }
  if (age < 3600) {
    return `${Math.floor(age / 60)} 分鐘前`;
  }
  return `${Math.floor(age / 3600)} 小時前`;
});

const label = computed(() => {
  if (props.status === "degraded") {
    return "無法取得";
  }
  return props.status === "stale" ? "可能過時" : relative.value;
});

// The full instant, with its zone, on hover and for screen readers: the relative form
// is for scanning, the absolute one is what gets pasted into a ticket.
const exact = computed(
  () => `${formatInstant(props.generatedAt)} (${localTimeZone()})`,
);
</script>

<template>
  <span
    class="freshness"
    :data-status="status"
    :title="exact"
    :aria-label="`資料時間 ${exact}${status === 'stale' ? '，可能過時' : ''}`"
  >
    <!-- A glyph as well as a colour, so the state survives greyscale and colour
         blindness. -->
    <i aria-hidden="true">{{
      status === "degraded" ? "⚠" : status === "stale" ? "!" : "·"
    }}</i>
    {{ label }}
  </span>
</template>

<style scoped>
.freshness {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.freshness i {
  font-style: normal;
  font-weight: 700;
}
.freshness[data-status="stale"] {
  color: var(--status-warning-fg);
}
.freshness[data-status="degraded"] {
  color: var(--status-error-fg);
}
</style>
