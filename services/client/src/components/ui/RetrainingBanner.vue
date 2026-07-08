<script setup>
// Inline notice that visible results still reflect a previous model while a
// segment re-train is in flight. Message goes in the default slot.
</script>

<template>
  <div class="retraining-banner" role="status">
    <i class="pi pi-sync" />
    <span><slot /></span>
  </div>
</template>

<style scoped>
.retraining-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  font-size: 12.5px;
  color: var(--text-color-secondary);
  background: var(--surface-inset);
  border: 1px solid var(--surface-border);
  border-left: 3px solid var(--running-color);
  border-radius: var(--radius-sm);
}
.retraining-banner i {
  color: var(--running-color);
  font-size: 13px;
}
</style>
