<script setup lang="ts">
// The account menu: who you are, personal settings, sign out.
//
// plan/28 §4 said "theme switching on other pages is provided by the account
// menu" — and then no account menu was built, so a bare `<select>` went into
// the header instead. That was wrong in a way worth naming: a global
// preference rendered as a permanent header control reads as something that
// applies to the page you are on, and it left the other three preferences with
// nowhere to live at all.
//
// Escape and focus return come from useFocusTrap, the same composable the
// dialog and the file drawer use.

import { computed, ref } from "vue";
import { RouterLink } from "vue-router";
import { ChevronDown, LogOut, Settings } from "lucide-vue-next";

import { useFocusTrap } from "../../composables/useFocusTrap";

const props = defineProps<{
  displayName: string;
  role: string;
}>();

const emit = defineEmits<{ logout: [] }>();

const open = ref(false);
const panel = ref<HTMLElement>();

useFocusTrap(panel, open, { onEscape: () => (open.value = false) });

// The initial, for the collapsed avatar. Takes the first character rather than
// the first ASCII letter: a display name is often not Latin here.
const initial = computed(() => [...props.displayName][0] ?? "?");
</script>

<template>
  <div class="account">
    <button
      type="button"
      class="trigger"
      :aria-expanded="open"
      aria-haspopup="menu"
      @click="open = !open"
    >
      <span class="avatar" aria-hidden="true">{{ initial }}</span>
      <span class="who">
        <span class="name">{{ displayName }}</span>
        <span class="role">{{ role }}</span>
      </span>
      <ChevronDown class="chevron" aria-hidden="true" />
    </button>

    <div v-if="open" class="catcher" @click="open = false" />
    <div v-if="open" ref="panel" class="panel" role="menu">
      <RouterLink
        :to="{ name: 'preferences' }"
        class="item"
        role="menuitem"
        @click="open = false"
      >
        <Settings class="icon" aria-hidden="true" />
        個人設定
      </RouterLink>
      <div class="divider" role="separator" />
      <button
        type="button"
        class="item"
        role="menuitem"
        @click="
          open = false;
          emit('logout');
        "
      >
        <LogOut class="icon" aria-hidden="true" />
        登出
      </button>
    </div>
  </div>
</template>

<style scoped>
.account {
  position: relative;
  display: inline-flex;
  min-width: 0;
}
.trigger {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: var(--density-control);
  max-width: 240px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--text-primary);
  min-width: 0;
}
.trigger:hover,
.trigger[aria-expanded="true"] {
  background: var(--surface-raised);
  border-color: var(--border-control);
}
.avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: var(--radius-pill);
  background: var(--accent-subtle);
  color: var(--accent-strong);
  font-size: 12px;
  font-weight: 650;
}
.who {
  display: grid;
  gap: 1px;
  min-width: 0;
  text-align: left;
}
.name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.role {
  font-size: 11px;
  color: var(--text-secondary);
  text-transform: capitalize;
}
.chevron {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  color: var(--text-secondary);
}

/* A transparent catcher rather than a document listener: it closes on any
   outside click without this component reasoning about which clicks count as
   outside, and it disappears with the menu. */
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
  min-width: 196px;
  display: grid;
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  box-shadow: var(--shadow-overlay);
}
.item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  min-height: var(--density-control);
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
  text-align: left;
  text-decoration: none;
}
.item:hover {
  background: var(--surface-default);
}
.icon {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  color: var(--text-secondary);
}
.divider {
  height: 1px;
  margin: 4px 2px;
  background: var(--border-subtle);
}
</style>
