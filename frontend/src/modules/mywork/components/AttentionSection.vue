<script setup lang="ts">
/**
 * One section of My Work (PX-49).
 *
 * **Three states, not two.** Empty, populated, and *unanswerable* — the third exists
 * because the "no eligible runner" section depends on the node registry, and when the
 * registry cannot be consulted the honest answer is "we did not look" rather than "none"
 * (ADR 0040 §2). Rendering the second as the first is the failure this component's own
 * test is about: "none" sends a person to do something else, and "we do not know" sends
 * them to reload.
 */
import { RouterLink } from "vue-router";

import AttentionBadge from "../../work/components/AttentionBadge.vue";
import type { SectionResult } from "../sections";

const props = defineProps<{ section: SectionResult }>();
</script>

<template>
  <section class="attention-section" :data-section="props.section.spec.key">
    <header>
      <h2>{{ props.section.spec.title }}</h2>
      <span v-if="!props.section.unavailable" class="count" data-count>
        {{ props.section.count }}
      </span>
      <p class="caption">{{ props.section.spec.caption }}</p>
    </header>

    <!-- Not an empty list. The reason is on screen, because a reader who sees "0" stops
         looking and a reader who sees this reloads. -->
    <p
      v-if="props.section.unavailable"
      class="unavailable"
      role="status"
      data-unavailable
    >
      {{ props.section.unavailable }}
    </p>
    <p v-else-if="props.section.items.length === 0" class="empty" data-empty>
      沒有等你的事。
    </p>
    <ul v-else>
      <li v-for="card in props.section.items" :key="card.id">
        <RouterLink
          :to="{
            name: 'project-work',
            params: { id: card.project_id ?? '' },
            query: { task: card.id },
          }"
          class="card-link"
          :data-card="card.card_ref"
        >
          <span class="ref">{{ card.card_ref }}</span>
          <span class="title">{{ card.title }}</span>
        </RouterLink>
        <AttentionBadge
          v-if="card.primary_attention"
          density="compact"
          :primary="card.primary_attention"
          :count="card.attention_count ?? 1"
        />
      </li>
    </ul>
  </section>
</template>

<style scoped>
.attention-section {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
  padding: var(--space-4);
}
.attention-section header {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0 var(--space-3);
  align-items: baseline;
  margin-bottom: var(--space-3);
}
.attention-section h2 {
  margin: 0;
  font-size: var(--font-md);
}
.count {
  min-width: 24px;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--surface-canvas);
  color: var(--text-secondary);
  font-size: var(--font-xs);
  font-variant-numeric: tabular-nums;
  text-align: center;
}
.caption {
  grid-column: 1 / -1;
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.unavailable,
.empty {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-sm);
}
/* The unanswerable state is marked, not merely worded: a reader scanning six sections
 * should be able to see that one of them is not an answer. */
.unavailable {
  border-left: 3px solid var(--attention-warning);
  padding-left: var(--space-3);
  color: var(--text-secondary);
}
.attention-section ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.attention-section li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.card-link {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  color: var(--text-primary);
  text-decoration: none;
}
.card-link:hover .title {
  text-decoration: underline;
}
.ref {
  flex: none;
  font-family: var(--font-mono);
  font-size: var(--font-xs);
  color: var(--text-muted);
}
.title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-sm);
}
</style>
