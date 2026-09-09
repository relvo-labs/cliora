<script setup lang="ts">
// A small menu behind an icon button. Built for one job: holding the actions
// that must not sit in the everyday primary position.
//
// Terminate is the reason it exists. It used to be a permanently visible red
// button in the work header, next to Reconnect and Request control — the three
// most routine controls on the page. Graphite §5 puts destructive actions in an
// action menu behind a confirmation that names the session, and that is not
// only about visual weight: a red button one pixel from Reconnect is a
// mis-click that stops a remote process.
//
// It reuses useFocusTrap for Escape and focus return. A menu is not a modal, so
// it does not scrim the page, but it has the same two obligations: Escape must
// close it, and closing must put focus back on the button that opened it.

import { computed, ref } from "vue";
import { MoreHorizontal } from "lucide-vue-next";

import { useFocusTrap } from "../../composables/useFocusTrap";
import UiIconButton from "./UiIconButton.vue";

withDefaults(defineProps<{ label?: string }>(), { label: "更多操作" });

const open = ref(false);
const panel = ref<HTMLElement>();

useFocusTrap(panel, open, { onEscape: () => (open.value = false) });
const expanded = computed(() => open.value);
</script>

<template>
  <div class="menu">
    <UiIconButton :label="label" :expanded="expanded" @click="open = !open">
      <MoreHorizontal />
    </UiIconButton>
    <!-- A transparent full-page catcher rather than a document listener: it
         closes on any outside click without this component having to reason
         about which clicks are "outside", and it disappears with the menu. -->
    <div v-if="open" class="catcher" @click="open = false" />
    <div v-if="open" ref="panel" class="panel" role="menu">
      <!-- The caller renders the items and calls `close` from each, so an
           action cannot leave the menu hanging open over the change it made. -->
      <slot :close="() => (open = false)" />
    </div>
  </div>
</template>

<style scoped>
.menu {
  position: relative;
  display: inline-flex;
}
.catcher {
  position: fixed;
  inset: 0;
  z-index: 14;
}
.panel {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 15;
  min-width: 200px;
  display: grid;
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  box-shadow: var(--shadow-overlay);
}
/* Applied to whatever the caller rendered, so a menu item does not need its own
   stylesheet in three different views. */
.panel :slotted(button) {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: var(--density-control);
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
  text-align: left;
}
.panel :slotted(button:hover:not(:disabled)) {
  background: var(--surface-default);
}
.panel :slotted(button:disabled) {
  color: var(--text-disabled);
  cursor: not-allowed;
}
.panel :slotted(button[data-danger]) {
  color: var(--status-error-fg);
}
.panel :slotted(button[data-danger]:hover:not(:disabled)) {
  background: var(--status-error-bg);
}
</style>
