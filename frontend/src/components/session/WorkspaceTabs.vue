<script setup lang="ts">
// Workspace centre-pane tab bar (WT-03). Presentation only: it owns no
// business state and never decides which panels exist — the view does.
//
// The whole bar is a single tab stop (roving tabindex), the same pattern the
// file tree uses: arrow keys move between tabs, Tab moves out of the bar.
// Activation follows focus because every panel is already mounted, so
// selecting one costs nothing.

import { nextTick, ref } from "vue";

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
      <button
        v-if="tab.closable"
        type="button"
        class="close"
        :aria-label="`關閉 ${tab.label}`"
        :tabindex="tab.id === active ? 0 : -1"
        @click="emit('close', tab.id)"
      >
        ×
      </button>
      <!-- Selection is marked by weight and an underline as well as colour
           (style.md §17: state is never colour alone). -->
      <span class="underline" aria-hidden="true" />
    </div>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  align-items: stretch;
  gap: 2px;
  border-bottom: 1px solid var(--border-default);
}
.tab {
  position: relative;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 4px 0 10px;
}
.tab button[role="tab"] {
  padding: 8px 2px;
  border: 0;
  background: none;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tab[data-active] button[role="tab"] {
  color: var(--text-primary);
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
  background: var(--action-primary);
}
.close {
  padding: 0 4px;
  border: 0;
  background: none;
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1;
}
.close:hover {
  color: var(--status-error);
}
</style>
