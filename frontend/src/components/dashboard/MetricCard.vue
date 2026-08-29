<script setup lang="ts">
// One big number with its title, freshness and state (style §10/§23, P4-08).
//
// The card owns the three presentations a block can need, which is why they are here
// rather than repeated per call site:
//
//   * **degraded** — no number at all, an explanation, and a retry. Showing 0 for a
//     figure that could not be read would be a fabrication.
//   * **stale** — the number *is* shown, marked as possibly out of date. It is real data,
//     just older than the contract lets it pass as current.
//   * **no data** — for a measurement nothing has reported yet: "—" and a caption, never
//     0%. "Nothing reported" and "zero" are different facts.

import { computed } from "vue";

import type { DashboardBlockStatus } from "../../api/dto";
import FreshnessBadge from "./FreshnessBadge.vue";

const props = defineProps<{
  title: string;
  // Null renders the no-data form rather than a zero.
  value: number | string | null;
  status: DashboardBlockStatus;
  generatedAt: string;
  now: number;
  icon?: string;
  caption?: string;
  errorCode?: string | null;
  // Suffix for the big number (e.g. "%"), kept out of `value` so the accessible name
  // can be assembled correctly.
  unit?: string;
  tone?: "neutral" | "good" | "warn" | "bad";
}>();

const emit = defineEmits<{ retry: [] }>();

const degraded = computed(() => props.status === "degraded");
const shown = computed(() =>
  props.value === null ? "—" : String(props.value),
);

// An explicit accessible name: a screen reader reaching a bare "12" out of its visual
// context learns nothing (style §23).
const accessibleName = computed(() => {
  if (degraded.value) {
    return `${props.title}：目前無法取得`;
  }
  if (props.value === null) {
    return `${props.title}：尚無資料`;
  }
  const suffix = props.unit ?? "";
  const stale = props.status === "stale" ? "，可能過時" : "";
  return `${props.title}：${props.value}${suffix}${stale}`;
});
</script>

<template>
  <section class="card" :data-tone="tone ?? 'neutral'" :data-status="status">
    <header>
      <h3>
        <span v-if="icon" class="icon" aria-hidden="true">{{ icon }}</span
        >{{ title }}
      </h3>
      <FreshnessBadge :status="status" :generated-at="generatedAt" :now="now" />
    </header>

    <template v-if="degraded">
      <p class="unavailable">暫時無法取得</p>
      <p class="reason">
        <code v-if="errorCode">{{ errorCode }}</code>
        <button type="button" class="retry" @click="emit('retry')">重試</button>
      </p>
    </template>
    <template v-else>
      <!-- The accessible name is a **sibling span**, not an `aria-label` on the `<p>`.
           ARIA prohibits `aria-label` on a `<p>` with no role, so the previous form was
           discarded by the accessibility tree and the reader heard the bare number — the
           opposite of what it was written for. `HD-04`'s axe scan reported it eight times
           on Home (one per fleet metric); it had been silent since the card was built,
           because a dropped label reads exactly like a card that never had one. -->
      <p class="value">
        <span class="sr-only">{{ accessibleName }}</span>
        <span aria-hidden="true"
          >{{ shown
          }}<small v-if="unit && value !== null">{{ unit }}</small></span
        >
      </p>
      <p v-if="value === null" class="caption">尚無資料</p>
      <p v-else-if="caption" class="caption">{{ caption }}</p>
      <!-- Stated in words, not implied by the badge's colour alone. -->
      <p v-if="status === 'stale'" class="stale-note">
        數字仍顯示，但可能不是最新狀態。
      </p>
    </template>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px 18px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
.card[data-status="degraded"] {
  border-color: var(--border-danger);
}
.card[data-status="stale"] {
  border-color: var(--status-busy);
}
header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}
h3 {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
}
.icon {
  font-size: 13px;
}
/* Same nine lines as `AuditView` and `ProjectWorkView`. Repeated rather than shared:
   these are scoped styles, and a fourth copy is cheaper than introducing a global
   utility sheet this codebase does not otherwise have. */
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
.value {
  margin: 0;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.value small {
  margin-left: 3px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-muted);
}
.card[data-tone="good"] .value {
  color: var(--status-online);
}
.card[data-tone="warn"] .value {
  color: var(--status-busy);
}
.card[data-tone="bad"] .value {
  color: var(--status-error);
}
.caption,
.stale-note,
.reason {
  margin: 0;
  color: var(--text-muted);
  font-size: 11px;
}
.stale-note {
  color: var(--status-busy);
}
.unavailable {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--status-error);
}
.reason {
  display: flex;
  align-items: center;
  gap: 8px;
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
