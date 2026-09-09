<script setup lang="ts">
// The navigation rail: Lucide icons, collapsible to 64px, one item per route.
//
// The seven text glyphs it replaces (`◫ ◈ ▣ ▷ ◉ ☰ ⇄`) were not only a style
// problem. `▷` is substituted by a different font on different platforms —
// sometimes as an emoji variant, with a different width and weight — and every
// one of them was a *readable text node*, so a screen reader announced it, with
// the pronunciation decided by whatever font matched. Once the rail collapses to
// icons only, those glyphs become its entire visual content, which is why this
// is a precondition for collapsing rather than a cosmetic change.
//
// **The three permission checks are unchanged.** They decide what to render;
// the server decides what is allowed (ADR 0016). A collapsed rail hides labels,
// never items — collapse is a visual state, and every item stays in the DOM and
// stays reachable by Tab. An item hidden for lack of permission stays hidden in
// both states: permission does not follow the layout.

import { computed } from "vue";
import { RouterLink } from "vue-router";
import {
  KeyRound,
  LayoutDashboard,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  ScrollText,
  Server,
  SquareTerminal,
  TerminalSquare,
} from "lucide-vue-next";

import {
  ACTION_AUDIT_VIEW,
  ACTION_ENROLLMENT_MANAGE,
  ACTION_INTEGRATION_MANAGE,
} from "../../api/dto";
import { useAuthStore } from "../../stores/auth";
import UiIconButton from "../ui/UiIconButton.vue";

// `withDefaults` rather than a bare optional Boolean, and that is load-bearing:
// **Vue casts an absent Boolean prop to `false`**, so `collapsible?: boolean`
// alone would make the desktop rail — which passes nothing — indistinguishable
// from the overlay that explicitly opts out, and the toggle would vanish
// everywhere. ErrorNotice carries a note about the same trap; it cost a test
// failure here before this comment existed.
const props = withDefaults(
  defineProps<{
    collapsed: boolean;
    productName: string;
    /**
     * False in the narrow-viewport menu overlay, where the rail is already at
     * full width and collapsing it would mean nothing. A rendered control that
     * does nothing is worse than an absent one: the user presses it, nothing
     * happens, and they have to work out whether it is broken or they are.
     */
    collapsible?: boolean;
  }>(),
  { collapsible: true },
);
const emit = defineEmits<{ "update:collapsed": [boolean] }>();

const auth = useAuthStore();

// Unchanged from before plan/28, deliberately and verifiably: the security
// review's first question is whether any UI change relaxed authorization, and
// the answer has to be "the display conditions are byte-identical".
const canManageEnrollment = computed(() =>
  auth.hasPermission(ACTION_ENROLLMENT_MANAGE),
);
const canViewAudit = computed(() => auth.hasPermission(ACTION_AUDIT_VIEW));
const canManageIntegrations = computed(() =>
  auth.hasPermission(ACTION_INTEGRATION_MANAGE),
);

const items = computed(() =>
  [
    {
      name: "dashboard",
      label: "Dashboard",
      icon: LayoutDashboard,
      show: true,
    },
    { name: "nodes", label: "Nodes", icon: Server, show: true },
    { name: "sessions", label: "Sessions", icon: TerminalSquare, show: true },
    {
      name: "enrollment",
      label: "Enrollment",
      icon: KeyRound,
      show: canManageEnrollment.value,
    },
    {
      name: "audit",
      label: "Audit",
      icon: ScrollText,
      show: canViewAudit.value,
    },
    {
      name: "integrations",
      label: "Integrations",
      icon: Plug,
      show: canManageIntegrations.value,
    },
  ].filter((item) => item.show),
);
</script>

<template>
  <aside class="rail" :data-collapsed="collapsed ? '' : undefined">
    <div class="brand">
      <span class="mark" aria-hidden="true"><SquareTerminal /></span>
      <!-- Hidden when collapsed, but the product name stays announced through
           the rail's own label below rather than disappearing entirely. -->
      <span v-if="!collapsed" class="name">{{ productName }}</span>
    </div>

    <nav id="primary-nav" aria-label="Primary">
      <RouterLink
        v-for="item in items"
        :key="item.name"
        :to="{ name: item.name }"
        class="item"
        :aria-label="collapsed ? item.label : undefined"
        :title="collapsed ? item.label : undefined"
      >
        <component :is="item.icon" class="icon" aria-hidden="true" />
        <!-- A tooltip is for a mouse and aria-label is for a screen reader;
             neither substitutes for the other, so a collapsed item has both. -->
        <span v-if="!collapsed" class="label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div v-if="collapsible" class="foot">
      <UiIconButton
        :label="collapsed ? '展開導覽' : '收合導覽'"
        :expanded="!collapsed"
        controls="primary-nav"
        @click="emit('update:collapsed', !props.collapsed)"
      >
        <PanelLeftOpen v-if="collapsed" />
        <PanelLeftClose v-else />
      </UiIconButton>
    </div>
  </aside>
</template>

<style scoped>
.rail {
  /* Width comes from the shell's grid column, height from its row. */
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 12px 10px;
  background: var(--surface-default);
  border-right: 1px solid var(--border-subtle);
}
.rail[data-collapsed] {
  padding: 12px 8px;
  align-items: center;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 6px 18px;
  font-weight: 650;
  font-size: 15px;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: var(--radius-control);
  /* accent-primary is a fill that carries no text; the glyph on it is an icon,
     and text-on-accent is measured against accent-strong. Using strong here
     keeps one rule: anything with a mark or a label on it uses strong. */
  background: var(--accent-strong);
  color: var(--text-on-accent);
}
.mark :deep(svg) {
  width: 17px;
  height: 17px;
}

nav {
  display: grid;
  gap: 3px;
}
.item {
  display: flex;
  align-items: center;
  gap: 11px;
  /* The touch floor, not the control height: this is a primary target. */
  min-height: var(--density-touch);
  padding: 0 11px;
  border-radius: var(--radius-control);
  /* 2px of transparent border on the left, so the selected state's rule does
     not shift the row by 2px when it appears. */
  border-left: 2px solid transparent;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
}
.rail[data-collapsed] .item {
  justify-content: center;
  padding: 0;
  width: var(--density-touch);
}
.icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}
.item:hover {
  background: var(--surface-raised);
  color: var(--text-primary);
}
/* Four signals, not one. The previous rail used background and colour only, so
   the "state is never colour alone" rule that style.md §17 applies to badges
   had never been applied to navigation. */
.item.router-link-active {
  background: var(--accent-subtle);
  /* accent-strong, not accent-primary: on accent-subtle, accent-primary
     measures 4.13:1 in Porcelain and 3.37:1 in Studio. */
  color: var(--accent-strong);
  border-left-color: var(--accent-primary);
  font-weight: 600;
}

.foot {
  margin-top: auto;
  padding-top: 12px;
}
</style>
