<template>
  <div class="table-scroll">
    <table>
      <slot />
    </table>
  </div>
</template>

<style scoped>
.table-scroll {
  max-width: 100%;
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-base);
}
:deep(th) {
  padding: 10px var(--space-4);
  border-bottom: 1px solid var(--border-default);
  color: var(--text-muted);
  background: var(--surface-default);
  font-size: var(--font-xs);
  font-weight: 600;
  letter-spacing: 0.02em;
  text-align: left;
  white-space: nowrap;
}
:deep(td) {
  padding: 14px var(--space-4);
  border-bottom: 1px solid var(--border-default);
}
:deep(tbody tr:last-child td) {
  border-bottom: 0;
}
:deep(tbody tr) {
  transition: background-color 0.14s ease;
}
:deep(tbody tr:hover) {
  background: var(--surface-default);
}
</style>
