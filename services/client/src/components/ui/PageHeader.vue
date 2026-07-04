<script setup>
defineProps({
  eyebrow: { type: String, default: null },
  title: { type: String, required: true },
  subtitle: { type: String, default: null }
})
</script>

<template>
  <div class="page-header">
    <div class="page-header-text">
      <div v-if="eyebrow" class="eyebrow mb-1">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="page-header-subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.page-header-subtitle {
  margin: 0.25rem 0 0;
  font-size: 0.84375rem;
  color: var(--text-color-secondary);
}
.page-header-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-shrink: 0;
}
</style>
