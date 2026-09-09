<script setup lang="ts">
// Two empties, not one.
//
// "Nothing exists yet" and "your filter matched nothing" need different words
// and different actions: the first wants a create entry, the second wants the
// filter cleared. `AsyncState` printed the same line for both — and for `stale`
// as well — so a user who had typed a search that matched nothing was told the
// list was empty, which is false and points at the wrong fix.
//
// The create entry appears only when the caller has the permission. That is a
// courtesy, not a control: the server refuses regardless (ADR 0016), and this
// component cannot be read as evidence that anything is allowed.

defineProps<{
  variant: "empty" | "no-results";
  title: string;
  /** What to do next. One sentence; the action goes in the `action` slot. */
  detail?: string;
}>();
</script>

<template>
  <div class="empty" :data-variant="variant">
    <p class="title">{{ title }}</p>
    <p v-if="detail" class="detail">{{ detail }}</p>
    <!-- A slot as well as `detail`, because several of these need a link or an
         interpolated count inside the sentence. -->
    <div v-if="$slots.default" class="detail"><slot /></div>
    <div v-if="$slots.action" class="action"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.empty {
  display: grid;
  gap: 8px;
  justify-items: center;
  padding: 48px 24px;
  text-align: center;
}
.title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.detail {
  margin: 0;
  max-width: 46ch;
  font-size: 12px;
  color: var(--text-secondary);
}
.action {
  margin-top: 4px;
}
</style>
