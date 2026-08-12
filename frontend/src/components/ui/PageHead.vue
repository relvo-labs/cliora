<template>
  <header class="page-head">
    <div class="titles">
      <h1><slot name="title" /></h1>
      <p v-if="$slots.subtitle"><slot name="subtitle" /></p>
    </div>
    <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.titles {
  min-width: 0;
}
h1 {
  margin: 0;
  font-size: var(--font-xl);
  line-height: 1.2;
}
p {
  margin: var(--space-1) 0 0;
  color: var(--text-muted);
  font-size: var(--font-sm);
}
.actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
}
@media (max-width: 700px) {
  .page-head {
    flex-direction: column;
  }
  .actions {
    justify-content: flex-start;
  }
}
</style>
