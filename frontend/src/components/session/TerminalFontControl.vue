<script setup lang="ts">
// Terminal font size, 12-20px.
//
// This is not a comfort setting. At 1024x768 the CLI panel measures 542px, and
// 14px/1.2 gives 28 rows there — under plan/09's floor of 30. Collapsing the
// work header to one row recovers about one row; the rest comes from here,
// because 13px/1.2 gives 30 at that size. So the control is part of how the
// small-viewport case is answered at all, which is why the release note tells
// people about it rather than leaving it to be found.
//
// Changing it resizes in place: `terminal.options.fontSize` and a refit. No new
// terminal, no reconnect (`FR-TERM-001.AC-16`).

import { Minus, Plus } from "lucide-vue-next";

import {
  TERMINAL_FONT_MAX,
  TERMINAL_FONT_MIN,
  usePreferencesStore,
} from "../../stores/preferences";
import UiIconButton from "../ui/UiIconButton.vue";

const preferences = usePreferencesStore();

function step(delta: number): void {
  preferences.setTerminalFontSize(preferences.terminalFontSize + delta);
}
</script>

<template>
  <div class="control">
    <UiIconButton
      label="縮小終端字級"
      :disabled="preferences.terminalFontSize <= TERMINAL_FONT_MIN"
      disabled-reason="已是最小字級 12px"
      @click="step(-1)"
    >
      <Minus />
    </UiIconButton>
    <!-- The value is text, not only a slider position: "14 px" is the fact, and
         a user who wants a specific size should be able to read it. -->
    <span class="value" aria-live="polite"
      >{{ preferences.terminalFontSize }} px</span
    >
    <UiIconButton
      label="放大終端字級"
      :disabled="preferences.terminalFontSize >= TERMINAL_FONT_MAX"
      disabled-reason="已是最大字級 20px"
      @click="step(1)"
    >
      <Plus />
    </UiIconButton>
  </div>
</template>

<style scoped>
.control {
  display: flex;
  align-items: center;
  gap: 2px;
}
.value {
  min-width: 42px;
  text-align: center;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}
/* The status bar is 28px, so the buttons shrink inside it; the hit area from
   UiIconButton still reaches the touch floor. */
.control :deep(button) {
  width: 24px;
  height: 24px;
}
.control :deep(svg) {
  width: 14px;
  height: 14px;
}
</style>
