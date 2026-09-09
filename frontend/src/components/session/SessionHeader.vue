<script setup lang="ts">
// The session's identity and its actions. Fixed height, two rows.
//
// What it replaces was a single flex row holding the session name, the runtime,
// the workspace path, two status badges, a control-role chip, zero to two
// posture labels and four buttons — with its height derived from its content.
// One long session name wrapped it, and wrapping pushed the whole work surface
// down, which on this page means the terminal gets shorter. Fixing the height
// is the point, not the tidiness.
//
// Three deliberate placements:
//
//   * **Status moved out.** Session state, connection and control are three
//     separate facts and they now live in the status bar, which is the layer
//     the information architecture puts them in.
//   * **Posture labels stayed.** They are not status — they are properties of
//     the node — and ADR 0023 D10 requires them visible *before* the user
//     types, so they cannot move into a menu or a tooltip.
//   * **Terminate moved into the action menu**, behind a confirmation that
//     names the session (Graphite §5). It was a permanently visible red button
//     beside Reconnect.
//
// The path truncates in the middle. Truncating the end removes the directory
// name, which is the part carrying the information; the full value stays in
// `title` and behind a copy button.

import { computed, ref } from "vue";
import { Check, Copy, RefreshCw, Server } from "lucide-vue-next";

import UiActionMenu from "../ui/UiActionMenu.vue";
import UiButton from "../ui/UiButton.vue";
import UiIconButton from "../ui/UiIconButton.vue";

const props = defineProps<{
  name: string;
  nodeName?: string;
  runtime: string;
  workspace: string;
  /** The node has its sandbox disabled (ADR 0023). */
  sandboxBypassed?: boolean;
  /** The node can escalate to root through sudo (ADR 0023). */
  privilegedNode?: boolean;
  canTakeover?: boolean;
  isViewer?: boolean;
  canRetry?: boolean;
  canTerminate?: boolean;
  busy?: boolean;
  /** 1024-1439px: one row, with the identity line behind a disclosure. */
  compact?: boolean;
}>();

const emit = defineEmits<{
  takeover: [];
  reconnect: [];
  terminate: [];
}>();

const copied = ref(false);
const detailsOpen = ref(false);

async function copyPath(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.workspace);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 1600);
  } catch {
    // No clipboard permission. The full path is already in `title`, so the
    // user is not stuck — and a failed copy is not worth an error banner.
  }
}

// Reversed for `direction: rtl` middle truncation, which needs the string's
// visual order flipped so the browser elides the middle rather than the end.
const identity = computed(() =>
  [props.nodeName, props.runtime].filter(Boolean).join(" · "),
);
</script>

<template>
  <header class="head" :data-compact="compact ? '' : undefined">
    <div class="row primary">
      <h1 :title="name">{{ name }}</h1>
      <div class="actions">
        <!-- Only when the user is read-only *and* the server said takeover is
             possible. Both conditions are unchanged from before plan/28. -->
        <UiButton
          v-if="canTakeover && isViewer"
          variant="secondary"
          @click="emit('takeover')"
        >
          取得控制權
        </UiButton>
        <UiButton
          v-if="canRetry"
          variant="secondary"
          @click="emit('reconnect')"
        >
          <template #icon><RefreshCw class="icon" /></template>
          重新連線
        </UiButton>
        <UiActionMenu label="Session 操作">
          <template #default="{ close }">
            <button
              type="button"
              role="menuitem"
              data-danger
              :disabled="!canTerminate || busy"
              @click="
                close();
                emit('terminate');
              "
            >
              終止 Session…
            </button>
          </template>
        </UiActionMenu>
      </div>
    </div>

    <!-- Second row: who and where. At 1024-1439px it collapses behind a
         disclosure so the header can be one 48px row — which measured out as
         24px recovered, about one terminal row at 14px/1.2. -->
    <div v-if="!compact || detailsOpen" class="row identity">
      <Server class="icon" aria-hidden="true" />
      <!-- The node name was not displayed at all before. The information
           architecture lists name, node, runtime and workspace together as the
           session's identity, and the node was the only one missing — the data
           was already fetched, just never rendered. -->
      <span class="who">{{ identity }}</span>
      <span class="sep" aria-hidden="true">·</span>
      <code class="path truncate-middle" :title="workspace">{{
        workspace
      }}</code>
      <UiIconButton
        :label="copied ? '已複製工作目錄路徑' : '複製工作目錄路徑'"
        @click="copyPath"
      >
        <Check v-if="copied" />
        <Copy v-else />
      </UiIconButton>
      <!-- Posture stays on this row and out of any menu: ADR 0023 D10 requires
           it in view before the user presses Enter. -->
      <span v-if="sandboxBypassed" class="posture" title="ADR 0023"
        >沙箱：已停用</span
      >
      <span v-if="privilegedNode" class="posture" title="ADR 0023"
        >此 Node 可提權（sudo）</span
      >
    </div>
    <button
      v-if="compact"
      type="button"
      class="disclose"
      :aria-expanded="detailsOpen"
      @click="detailsOpen = !detailsOpen"
    >
      {{ detailsOpen ? "收起 Session 資訊" : "顯示 Session 資訊" }}
    </button>
  </header>
</template>

<style scoped>
.head {
  /* Fixed, and flex-column rather than a row template: plan/09 D3 forbids a
     panel sizing itself with grid rows, and the same reasoning applies to a
     header whose second row is conditional. */
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  height: var(--layout-workhead);
  flex-shrink: 0;
  overflow: hidden;
}
.head[data-compact] {
  height: var(--layout-workhead-compact);
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.primary {
  gap: 12px;
}
h1 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.01em;
  /* Truncates at the end: a name's beginning is what identifies it, unlike a
     path. The full value is in `title`. */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-shrink: 0;
}
.icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
}
.identity {
  font-size: 12px;
  color: var(--text-secondary);
}
.who {
  white-space: nowrap;
}
.sep {
  color: var(--text-disabled);
}
.path {
  font-family: var(--font-mono);
  font-size: 11px;
  max-width: min(46ch, 100%);
}
.posture {
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  background: var(--status-warning-bg);
  border: 1px solid var(--status-warning-border);
  color: var(--status-warning-fg);
  font-size: 11px;
  white-space: nowrap;
}
.disclose {
  align-self: flex-start;
  padding: 0;
  border: 0;
  background: none;
  color: var(--accent-strong);
  font-size: 11px;
}
</style>
