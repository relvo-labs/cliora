<script setup lang="ts">
// A status pill: dot, text, and a 1px outline.
//
// Rewritten in plan/28 for two reasons that were both invisible before there
// was a token table.
//
// 1. **Six of its eight colour pairs were under 4.5:1** (online 3.13,
//    degraded 2.63, error 3.50, offline 3.75, connected 4.24,
//    reconnecting 3.86). That was not carelessness: `style.md` §17 said "Online
//    Green" and never said green *on what*, so each background was invented
//    here, and nothing in the repository could disagree. §17 now specifies a
//    foreground/background/border triplet per semantic, and the contrast test
//    holds it.
//
// 2. **Three different vocabularies shared one `data-status` attribute** — node
//    state, browser connection state and session state — so `exited` and `gap`
//    ended up on the same CSS rule by coincidence rather than by meaning. Here
//    the caller says which vocabulary it is speaking, and each maps onto one of
//    five semantics. The *label* is not shared: "已結束" and "輸出中斷" are
//    different facts even where both are red.
//
// The outline is not decoration. The fill measures only 1.13-1.19:1 against a
// panel, so without it the pill has no perceptible edge and the label appears
// to float.

import { computed } from "vue";

export type StatusTone = "success" | "warning" | "error" | "info" | "neutral";

// Which vocabulary `status` belongs to.
//
// `token` and `runtime` were added while doing this rewrite, and finding them
// was the point of separating the vocabularies at all: EnrollmentView was
// passing token lifecycle values through the *node* map to borrow its colours,
// and NodeDetailView was doing the same for runtime availability. That worked
// only while every vocabulary shared one label table. Once labels became
// per-vocabulary, an active enrolment token would have rendered as "線上" —
// the colour was right and the sentence was false.
export type StatusKind =
  | "node"
  | "connection"
  | "session"
  | "token"
  | "runtime";

const props = withDefaults(
  defineProps<{
    /** A raw value from the API or the terminal composable. */
    status: string;
    kind?: StatusKind;
    /**
     * `status` for something that changes while the user watches (a connection
     * dropping); nothing for a static label in a table cell. A table of twenty
     * live regions announces twenty things nobody asked about.
     */
    live?: boolean;
  }>(),
  { kind: "node" },
);

// Colour is one of five semantics. Text is per vocabulary — see the note above.
const TONES: Record<StatusKind, Record<string, StatusTone>> = {
  node: {
    online: "success",
    degraded: "warning",
    offline: "neutral",
    disabled: "neutral",
    error: "error",
  },
  connection: {
    idle: "neutral",
    connecting: "info",
    connected: "success",
    reconnecting: "warning",
    disconnected: "error",
    exited: "neutral",
    gap: "warning",
  },
  session: {
    creating: "info",
    starting: "info",
    running: "success",
    active: "success",
    stopped: "neutral",
    exited: "neutral",
    terminated: "neutral",
    failed: "error",
    error: "error",
  },
  token: {
    active: "success",
    expired: "neutral",
    exhausted: "neutral",
    revoked: "error",
  },
  runtime: {
    available: "success",
    unavailable: "neutral",
  },
};

const LABELS: Record<StatusKind, Record<string, string>> = {
  node: {
    online: "線上",
    degraded: "降級",
    offline: "離線",
    disabled: "已停用",
    error: "錯誤",
  },
  connection: {
    idle: "尚未連線",
    connecting: "連線中",
    connected: "已連線",
    reconnecting: "重新連線中",
    disconnected: "已斷線",
    // Not "已結束": from the browser's point of view the remote process ended.
    // A session that has stopped and a browser that has lost its socket are
    // different situations with different next actions, and collapsing the two
    // labels is what makes Reconnect look like Restart.
    exited: "程序已結束",
    gap: "輸出中斷",
  },
  session: {
    creating: "建立中",
    starting: "啟動中",
    running: "執行中",
    active: "執行中",
    stopped: "已停止",
    exited: "已結束",
    terminated: "已終止",
    failed: "失敗",
    error: "錯誤",
  },
  token: {
    active: "啟用中",
    expired: "已過期",
    exhausted: "已用完",
    revoked: "已撤銷",
  },
  runtime: {
    available: "可用",
    unavailable: "不可用",
  },
};

const tone = computed<StatusTone>(
  () => TONES[props.kind][props.status] ?? "neutral",
);
// Falls back to the raw value rather than to an empty pill: an unmapped status
// showing its own name is debuggable, and a blank pill is not.
const label = computed(() => LABELS[props.kind][props.status] ?? props.status);
</script>

<template>
  <span class="badge" :data-tone="tone" :role="live ? 'status' : undefined">
    <i class="dot" aria-hidden="true" />
    <!-- Always text alongside the dot, so meaning never rests on colour
         (WCAG 1.4.1). -->
    <span class="text">{{ label }}</span>
    <!-- warning carries a mark as well as a hue: in one of the five themes the
         brand colour is a near neighbour of warning, and in all of them colour
         alone is not allowed to carry the semantic. -->
    <span v-if="tone === 'warning'" class="mark" aria-hidden="true">!</span>
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  height: 24px;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid;
  border-radius: var(--radius-pill);
  font-size: 12px;
  white-space: nowrap;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentcolor;
  flex-shrink: 0;
}
.mark {
  font-weight: 700;
}
.badge[data-tone="success"] {
  color: var(--status-success-fg);
  background: var(--status-success-bg);
  border-color: var(--status-success-border);
}
.badge[data-tone="warning"] {
  color: var(--status-warning-fg);
  background: var(--status-warning-bg);
  border-color: var(--status-warning-border);
}
.badge[data-tone="error"] {
  color: var(--status-error-fg);
  background: var(--status-error-bg);
  border-color: var(--status-error-border);
}
.badge[data-tone="info"] {
  color: var(--status-info-fg);
  background: var(--status-info-bg);
  border-color: var(--status-info-border);
}
.badge[data-tone="neutral"] {
  color: var(--status-neutral-fg);
  background: var(--status-neutral-bg);
  border-color: var(--status-neutral-border);
}
</style>
