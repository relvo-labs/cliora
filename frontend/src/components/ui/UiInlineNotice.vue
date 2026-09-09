<script setup lang="ts">
// A notice that stays where the thing it is about is, and does not disappear.
//
// This is half of the split of `AsyncState`, which expressed nine states
// through one prop and rendered `<strong>{{ state }}</strong>` — the state's
// internal name, in English, lower-cased, printed on screen for the user. The
// nine states need completely different *actions*, so no single component could
// be all of them.
//
// The other half of the rule lives in Toast: failures never go to a Toast. An
// error that removes itself after three seconds is an error the user may never
// have seen, so upload failures, terminate failures and connection failures all
// come here or to ErrorNotice, and stay put.

const props = withDefaults(
  defineProps<{
    tone?: "info" | "warning" | "error" | "stale";
    title?: string;
    /**
     * Only a string. Deliberately not `unknown`: given a wider type, the next
     * caller passes a caught exception straight through, and an exception's
     * message can carry server internals. Turning an error into a sentence a
     * user can act on is the caller's job (see utils/errorCatalog).
     */
    message?: string;
  }>(),
  { tone: "info" },
);
</script>

<template>
  <div
    class="notice"
    :data-tone="tone"
    :role="props.tone === 'error' ? 'alert' : 'status'"
  >
    <span class="mark" aria-hidden="true">{{
      tone === "error" ? "!" : tone === "warning" ? "!" : "i"
    }}</span>
    <div class="body">
      <p v-if="title" class="title">{{ title }}</p>
      <p v-if="message" class="message">{{ message }}</p>
      <slot />
    </div>
    <!-- Any retry or dismiss the caller wants. Dismiss is the caller's choice
         and never a timer: nothing here removes itself. -->
    <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.notice {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 12px;
  border: 1px solid;
  border-radius: var(--radius-panel);
  font-size: 12px;
}
.mark {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  border-radius: var(--radius-pill);
  border: 1px solid currentcolor;
  font-size: 10px;
  font-weight: 700;
  margin-top: 1px;
}
.body {
  display: grid;
  gap: 4px;
  min-width: 0;
  flex: 1;
}
.title {
  margin: 0;
  font-weight: 600;
}
.message {
  margin: 0;
  overflow-wrap: anywhere;
}
.actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.notice[data-tone="info"] {
  color: var(--status-info-fg);
  background: var(--status-info-bg);
  border-color: var(--status-info-border);
}
.notice[data-tone="warning"] {
  color: var(--status-warning-fg);
  background: var(--status-warning-bg);
  border-color: var(--status-warning-border);
}
.notice[data-tone="error"] {
  color: var(--status-error-fg);
  background: var(--status-error-bg);
  border-color: var(--status-error-border);
}
/* `stale` is not an error: the data on screen is still true, it is just not the
   newest. It reads as neutral so it does not compete with a real failure
   elsewhere on the page. */
.notice[data-tone="stale"] {
  color: var(--status-neutral-fg);
  background: var(--status-neutral-bg);
  border-color: var(--status-neutral-border);
}
</style>
