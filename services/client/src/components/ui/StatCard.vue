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
  padding: 16px 18px;
}
.stat-card-label {
  margin-bottom: 8px;
}
.stat-card-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--text-color);
}
.stat-card-value--error {
  color: var(--error-text-color);
}
.stat-card-caption {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-color-muted-2);
}
</style>
