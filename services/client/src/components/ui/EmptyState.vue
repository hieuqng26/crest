<script setup>
// First-class empty state per design.md: dashed border, muted icon, one
// sentence. Drop inside a bare .panel (or any container) instead of
// hand-rolling a centered <p>.
defineProps({
  icon: { type: String, default: 'pi pi-inbox' },
})
</script>

<template>
  <div class="empty-state">
    <i :class="icon" />
    <p><slot /></p>
  </div>
</template>

<style scoped>
.empty-state {
  margin: 16px;
  padding: 28px 20px;
  text-align: center;
  color: var(--text-color-muted);
  border: 1px dashed var(--surface-border-input);
  border-radius: var(--radius-sm);
}
.empty-state i {
  font-size: 22px;
  display: block;
  margin-bottom: 8px;
  opacity: 0.6;
}
.empty-state p {
  margin: 0;
  font-size: 13px;
}
</style>
