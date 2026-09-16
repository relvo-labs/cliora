<script setup lang="ts">
// The status bar. Specified in style.md §9 and §12 since P0, and never built —
// `tokens.css` even carried a `--layout-status` token with the comment "Not in
// use". plan/28 builds it.
//
// It shows three things **separately**, and that is the whole point:
//
//   Session state      creating / running / exited / failed / terminated
//   Browser connection connecting / connected / reconnecting / disconnected
//   Control            you have control / read-only (someone else holds it)
//
// Combining them into one green "OK" light loses information that changes what
// the user should do. "Session running + disconnected" is not "Session ended":
// the first wants Reconnect, and on the second Reconnect does nothing. The
// shared design foundation states the rule ("分開描述；不要合成一個綠色『正常』")
// and `FR-TERM-005.AC-06` now carries it.
//
// Before this, the three were three chips crowded into the work header's
// `.meta`, beside the session name, runtime, workspace path and two posture
// labels — so one long session name pushed them onto a second line and the
// header, whose height came from its content, grew and took it from the
// terminal.
//
// The 28px is not free: it is roughly 1.7 terminal rows, and it is counted in
// the row budget that measured 35 rows at 14px/1.2.

import StatusBadge from "../common/StatusBadge.vue";
import type {
  TerminalRole,
  TerminalStatus,
} from "../../composables/useTerminalSession";

defineProps<{
  /** From the API. Absent while the session is still loading. */
  sessionStatus?: string;
  /** From the terminal composable — the browser's socket, not the session. */
  connection: TerminalStatus;
  role: TerminalRole;
  /** Shown while the session itself could not be loaded. */
  loadError?: boolean;
}>();
</script>

<template>
  <footer class="status-bar">
    <div class="group">
      <!-- Session state. When the session could not be loaded the bar says so
           rather than going blank: the workspace container is never unmounted
           (a veil covers it), so a blank status bar under a veil reads as
           "everything is fine behind here". -->
      <span class="cell">
        <span class="key">Session</span>
        <StatusBadge
          v-if="sessionStatus"
          :status="sessionStatus"
          kind="session"
          live
        />
        <span v-else-if="loadError" class="plain error">無法載入</span>
        <span v-else class="plain">載入中</span>
      </span>

      <!-- Browser connection. A different fact from the one above. -->
      <span class="cell">
        <span class="key">連線</span>
        <StatusBadge :status="connection" kind="connection" live />
      </span>

      <!-- Control. Always words: "read-only" is a permission fact, and a colour
           cannot say who holds the write lock. -->
      <span class="cell">
        <span class="key">控制權</span>
        <span class="plain" :class="{ accent: role === 'writer' }">{{
          role === "writer" ? "你有控制權" : "唯讀（他人持有）"
        }}</span>
      </span>
    </div>

    <!-- Terminal font size and theme. They live here rather than in the global
         header because they only mean anything on a page that has a terminal;
         the header's own theme switcher covers the other ten pages. -->
    <div class="group end"><slot name="preferences" /></div>
  </footer>
</template>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: var(--layout-status);
  flex-shrink: 0;
  padding: 0 4px;
  font-size: 11px;
  color: var(--text-secondary);
  overflow: hidden;
}
.group {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.cell {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.key {
  color: var(--text-secondary);
}
.plain {
  color: var(--text-primary);
}
.plain.accent {
  color: var(--accent-strong);
}
.plain.error {
  color: var(--status-error-fg);
}
/* The badges are 24px inside a 28px bar, so they scale down rather than
   overflow it. */
.cell :deep(.badge) {
  height: 20px;
  padding: 0 7px;
  font-size: 11px;
}
/* Below 768px the preference controls give up their space first: the three
   states are information, and the two controls are also available on the
   preferences page. The three state *values* stay — they are three of the four
   facts the session header contract requires to remain visible. */
@media (max-width: 767px) {
  .group.end {
    display: none;
  }
  /* Visually hidden, still announced. `display: none` took the labels out of
     the accessibility tree along with the layout, which left a screen reader
     with three unlabelled values — the readings, with no way to tell which was
     the session and which was the connection (plan/29 MS-06). */
  .key {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
}
</style>
