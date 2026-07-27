<script setup lang="ts">
import AsyncState from "../components/common/AsyncState.vue";
import StatusBadge from "../components/common/StatusBadge.vue";
const states = [
  "idle",
  "loading",
  "success",
  "empty",
  "stale",
  "offline",
  "forbidden",
  "partial",
  "error",
] as const;
const statuses = ["connected", "reconnecting", "disconnected", "exited", "gap"];
</script>
<template>
  <section class="showcase">
    <header>
      <span>Foundation</span>
      <h1>Semantic token showcase</h1>
      <p>
        States remain understandable without color and every control has a
        visible focus treatment.
      </p>
    </header>
    <h2>Terminal states</h2>
    <div class="row">
      <StatusBadge v-for="status in statuses" :key="status" :status="status" />
    </div>
    <h2>Async states</h2>
    <div class="grid">
      <AsyncState v-for="state in states" :key="state" :state="state" />
    </div>
    <h2>Controls</h2>
    <div class="row">
      <button>Default</button><button class="primary">Primary</button
      ><button disabled>Disabled</button
      ><button aria-busy="true">Loading…</button
      ><button class="danger">Error action</button>
    </div>
  </section>
</template>
<style scoped>
.showcase {
  padding: 32px;
  max-width: 1100px;
}
.showcase header span {
  color: #4e8593;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.showcase h1 {
  margin: 7px 0;
  font-size: 28px;
}
.showcase p {
  color: var(--text-muted);
}
h2 {
  margin-top: 30px;
  font-size: 15px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
button {
  padding: 9px 13px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-elevated);
}
button.primary {
  background: var(--action-primary);
  color: white;
}
button.danger {
  border-color: var(--border-danger);
  color: #b34242;
}
button:disabled {
  cursor: not-allowed;
  color: var(--text-muted);
  background: #e9edf2;
}
@media (max-width: 850px) {
  .grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
