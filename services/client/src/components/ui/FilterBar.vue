<script setup>
// Inset strip that holds page-scope FilterField controls above a results
// panel. Filters live above the table, never inside it (design.md).
</script>

<template>
  <div class="filter-bar">
    <slot />
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
  background: var(--surface-inset);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
}
</style>
