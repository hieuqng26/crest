<script setup>
// IFRS 9 stage pill. Custom (not PrimeVue Tag): the stage colorways —
// stage 2 = ink/yellow, stage 3 = error/white — don't map to Tag severities.
defineProps({
  stage: { type: [Number, String], required: true },
})
</script>

<template>
  <span class="stage-tag font-mono" :class="`stage-tag--${stage}`">STAGE {{ stage }}</span>
</template>

<style scoped>
.stage-tag {
  display: inline-block;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  border-radius: var(--radius-sm);
}
.stage-tag--1 {
  background: var(--surface-card);
  color: var(--text-color-secondary);
  border: 1px solid var(--surface-border-input);
}
.stage-tag--2 {
  background: var(--ink);
  color: var(--yellow);
}
.stage-tag--3 {
  background: var(--error-color);
  color: #fff;
}
</style>
