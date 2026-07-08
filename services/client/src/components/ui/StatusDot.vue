<script setup>
import { computed } from 'vue'

const props = defineProps({
  // Backend status values map directly: queued | running | success | failed
  status: { type: String, required: true },
  label: { type: String, default: null },
  size: { type: Number, default: 8 }
})

const STATUS_MAP = {
  success:  { dot: 'var(--success-color)', text: 'var(--success-text-color)', label: 'Success' },
  failed:   { dot: 'var(--error-color)',   text: 'var(--error-text-color)',   label: 'Failed' },
  error:    { dot: 'var(--error-color)',   text: 'var(--error-text-color)',   label: 'Failed' },
  running:  { dot: 'var(--running-color)', text: 'var(--running-text-color)', label: 'Running' },
  queued:   { dot: 'var(--queued-color)',  text: 'var(--queued-text-color)',  label: 'Queued' },
  deleting: { dot: 'var(--deleting-color)', text: 'var(--deleting-text-color)', label: 'Deleting…', pulse: true }
}

const config = computed(() => STATUS_MAP[props.status] || STATUS_MAP.queued)
</script>

<template>
  <span class="status-dot-wrap">
    <span
      class="status-dot"
      :class="{ 'status-dot--pulse': config.pulse }"
      :style="{ backgroundColor: config.dot, width: size + 'px', height: size + 'px' }"
    ></span>
    <span class="status-text" :style="{ color: config.text }">{{ label || config.label }}</span>
  </span>
</template>

<style scoped>
.status-dot-wrap {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.status-dot {
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot--pulse {
  animation: status-dot-pulse 1s ease-in-out infinite;
}
@keyframes status-dot-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.35; }
}
.status-text {
  font-size: 12px;
  font-weight: 600;
}
</style>
