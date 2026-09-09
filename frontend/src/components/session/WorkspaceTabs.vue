<script setup lang="ts">
// Workspace centre-pane tab bar (WT-03). Presentation only: it owns no
// business state and never decides which panels exist — the view does.
//
// The whole bar is a single tab stop (roving tabindex), the same pattern the
// file tree uses: arrow keys move between tabs, Tab moves out of the bar.
// Activation follows focus because every panel is already mounted, so
// selecting one costs nothing.

import { nextTick, ref } from "vue";
import { X } from "lucide-vue-next";

import UiIconButton from "../ui/UiIconButton.vue";

export interface WorkspaceTab {
  id: string;
  label: string;
  // Full path or long form; shown on hover. Never a node absolute path.
  title?: string;
  closable?: boolean;
}

const props = defineProps<{ tabs: WorkspaceTab[]; active: string }>();
const emit = defineEmits<{ select: [id: string]; close: [id: string] }>();

const buttons = ref<HTMLButtonElement[]>([]);

function select(id: string): void {
  if (id !== props.active) emit("select", id);
}

async function move(delta: number, absolute?: "first" | "last"): Promise<void> {
  const index = props.tabs.findIndex((tab) => tab.id === props.active);
  if (index < 0) return;
  const next =
    absolute === "first"
      ? 0
      : absolute === "last"
        ? props.tabs.length - 1
        : (index + delta + props.tabs.length) % props.tabs.length;
  select(props.tabs[next].id);
  await nextTick();
  buttons.value[next]?.focus();
}

function onKeydown(event: KeyboardEvent): void {
  const handlers: Record<string, () => void> = {
    ArrowRight: () => void move(1),
    ArrowLeft: () => void move(-1),
    Home: () => void move(0, "first"),
    End: () => void move(0, "last"),
  };
  const handler = handlers[event.key];
  if (!handler) return;
  event.preventDefault();
  handler();
}
</script>

<template>
  <div class="tabs" role="tablist" aria-label="工作區面板" @keydown="onKeydown">
    <div
      v-for="tab in tabs"
      :key="tab.id"
      class="tab"
      :data-active="tab.id === active || undefined"
    >
      <button
        :id="`tab-${tab.id}`"
        ref="buttons"
        type="button"
        role="tab"
        :aria-selected="tab.id === active"
        :aria-controls="`panel-${tab.id}`"
        :tabindex="tab.id === active ? 0 : -1"
        :title="tab.title"
        @click="select(tab.id)"
      >
        {{ tab.label }}
      </button>
      <UiIconButton
        v-if="tab.closable"
        class="close"
        variant="on-terminal"
        :label="`關閉 ${tab.label}`"
        @click="emit('close', tab.id)"
      >
        <X />
      </UiIconButton>
      <!-- Selection is marked by weight and an underline as well as colour
           (style.md §17: state is never colour alone). -->
      <span class="underline" aria-hidden="true" />
    </div>
    <!-- Right-hand controls (the file drawer's open button). Outside the
         tablist's roving tabindex on purpose: it is not a tab, so the arrow
         keys must not reach it. -->
    <div v-if="$slots.end" class="end"><slot name="end" /></div>
  </div>
</template>

<style scoped>
/* Fixed height, and `flex-shrink: 0`. It used to be content-derived at about
   33px, so anything that changed a tab's line box changed the height of the
   terminal below it — the class of bug plan/09 spent a phase on. */
.tabs {
  display: flex;
  align-items: stretch;
  gap: 2px;
  height: var(--layout-tabs);
  flex-shrink: 0;
  padding-right: 6px;
  /* The strip sits on the terminal, not on a panel: in a light theme a panel
     background here would put a white band above a dark terminal, and the panel
     text colour would be near-black on it. */
  background: var(--surface-default);
  border-bottom: 1px solid var(--border-subtle);
}
.end {
  display: flex;
  align-items: center;
  margin-left: auto;
}
.tab {
  position: relative;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 4px 0 12px;
}
/* The selected tab is the one cell that carries the terminal's background up
   into the strip, so the panel below reads as continuous with it. Porcelain's
   own style document names this: the active tab uses the dark terminal
   background with light-theme-on-dark text, which is what --text-on-terminal
   exists for. Doing it the other way round — a light tab over a dark terminal —
   puts a hard edge exactly where the eye is trying to follow content. */
.tab[data-active] {
  background: var(--terminal-background);
}
.tab button[role="tab"] {
  padding: 0 2px;
  border: 0;
  background: none;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* Four signals for the selected tab — colour, background, underline and
   weight — not one. */
.tab[data-active] button[role="tab"] {
  color: var(--text-on-terminal);
  font-weight: 650;
}
.underline {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: transparent;
}
.tab[data-active] .underline {
  /* accent-primary: a 2px fill that carries no text, which is exactly what that
     token is for. */
  background: var(--accent-primary);
}
.close {
  width: 22px;
  height: 22px;
}
.close :deep(svg) {
  width: 13px;
  height: 13px;
}
</style>
