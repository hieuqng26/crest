<script setup>
// Train/validation split control — a labelled range slider with the yellow
// accent (design.md). Reusable wherever a train% / val% split is chosen.
defineProps({
  modelValue: { type: Number, default: 80 },
  min: { type: Number, default: 50 },
  max: { type: Number, default: 100 },
  step: { type: Number, default: 5 },
})
const emit = defineEmits(['update:modelValue'])
const onInput = (e) => emit('update:modelValue', Number(e.target.value))
</script>

<template>
  <div class="split-slider">
    <div class="split-slider-label">
      Data split — <span class="font-mono">train {{ modelValue }}% / val {{ 100 - modelValue }}%</span>
    </div>
    <input
      type="range"
      :min="min"
      :max="max"
      :step="step"
      :value="modelValue"
      class="split-slider-input"
      @input="onInput"
    />
  </div>
</template>

<style scoped>
.split-slider-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-color-muted);
  margin-bottom: 10px;
}
.split-slider-input {
  width: 100%;
  height: 20px;
  accent-color: var(--yellow);
  cursor: pointer;
  margin: 0;
  display: block;
}
</style>
