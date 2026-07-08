<script setup>
// One labeled control inside a FilterBar: 11px uppercase field label above
// whatever input/select goes in the slot.
defineProps({
  label: { type: String, required: true },
})
</script>

<template>
  <div class="filter-field">
    <label class="field-label">{{ label }}</label>
    <slot />
  </div>
</template>

<style scoped>
.filter-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 200px;
}
.field-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-color-muted);
}
</style>
