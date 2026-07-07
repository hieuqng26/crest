<script setup>
defineProps({
  modelValue: { type: String, default: 'All' },
  options: { type: Array, default: () => ['All', 'Baseline', 'Adverse', 'Severely Adverse'] }
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div class="scenario-chips">
    <button
      v-for="opt in options"
      :key="opt"
      type="button"
      class="scenario-chip"
      :class="{ 'is-active': modelValue === opt }"
      @click="emit('update:modelValue', opt)"
    >
      {{ opt }}
    </button>
  </div>
</template>

<style scoped>
.scenario-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.scenario-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 2px;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.05em;
  cursor: pointer;
  border: 1px solid var(--surface-border-input);
  background: transparent;
  color: var(--text-color-muted);
  transition: border-color 0.15s ease;
  line-height: 1.4;
}

.scenario-chip:hover {
  border-color: var(--ink);
}

.scenario-chip.is-active {
  background: var(--ink);
  color: #fff;
  border-color: var(--ink);
}
</style>
