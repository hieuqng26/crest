<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  caption: { type: String, default: null },
  tone: { type: String, default: 'default' } // 'default' | 'error'
})
</script>

<template>
  <div class="stat-card card--emphasis">
    <div class="eyebrow stat-card-label">{{ label }}</div>
    <div class="stat-card-value font-mono" :class="{ 'stat-card-value--error': tone === 'error' }">
      {{ value }}
    </div>
    <div v-if="caption" class="stat-card-caption">{{ caption }}</div>
  </div>
</template>

<style scoped>
.stat-card {
  padding: 1rem 1.125rem;
}
.stat-card-label {
  margin-bottom: 0.625rem;
}
.stat-card-value {
  font-size: 1.5rem;
  font-weight: 600;
  line-height: 1.2;
  color: var(--text-color);
}
.stat-card-value--error {
  color: var(--error-text-color);
}
.stat-card-caption {
  margin-top: 0.375rem;
  font-size: 0.75rem;
  color: var(--text-color-muted-2);
}
</style>
