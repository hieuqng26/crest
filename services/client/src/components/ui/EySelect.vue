<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number, Boolean, Array, Object], default: null },
  options: { type: Array, required: true },
  optionLabel: { type: [String, Function], default: null }, // string key, fn(opt), or null = use whole option as string
  optionValue: { type: String, default: null },   // null = use the whole option as value
  multiple: { type: Boolean, default: false },
  placeholder: { type: String, default: 'Select…' },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  filter: { type: Boolean, default: false },
  showClear: { type: Boolean, default: false },
  showToggleAll: { type: Boolean, default: false }, // multi only
  triggerLabel: { type: String, default: null },    // override computed trigger text (multi)
  maxSelectedLabels: { type: Number, default: 3 },  // single display max count (multi)
})

const emit = defineEmits(['update:modelValue'])

// ── value helpers ─────────────────────────────────────────────────────────────
const getLabel  = (opt) => {
  if (typeof props.optionLabel === 'function') return props.optionLabel(opt)
  if (props.optionLabel) return opt?.[props.optionLabel] ?? String(opt ?? '')
  return String(opt ?? '')
}
const getValue  = (opt) => props.optionValue ? opt?.[props.optionValue] : opt
const sameValue = (a, b) => {
  if (a === b) return true
  if (a == null || b == null) return false
  if (typeof a === 'object' && typeof b === 'object') return JSON.stringify(a) === JSON.stringify(b)
  return String(a) === String(b)
}

const isSelected = (opt) => {
  const v = getValue(opt)
  if (props.multiple) {
    return Array.isArray(props.modelValue) && props.modelValue.some((sel) => sameValue(sel, v))
  }
  return sameValue(props.modelValue, v)
}

// ── multi: all-selected ───────────────────────────────────────────────────────
const allSelected = computed(() =>
  props.multiple &&
  props.options.length > 0 &&
  props.options.every((o) => isSelected(o))
)
const selectedCount = computed(() =>
  props.multiple && Array.isArray(props.modelValue) ? props.modelValue.length : 0
)

// ── trigger label ─────────────────────────────────────────────────────────────
const computedTriggerLabel = computed(() => {
  if (props.triggerLabel) return props.triggerLabel
  if (!props.multiple) {
    if (props.modelValue == null || props.modelValue === '') return null
    const found = props.options.find((o) => sameValue(getValue(o), props.modelValue))
    return found ? getLabel(found) : null
  }
  const n = selectedCount.value
  const total = props.options.length
  if (n === 0) return null
  if (n === total) return `All (${total})`
  return `${n}/${total}`
})

// ── open / close ──────────────────────────────────────────────────────────────
const open = ref(false)
const triggerRef = ref(null)
const panelRef   = ref(null)
const filterText = ref('')

const panelStyle = ref({ top: '0px', left: '0px', width: '0px' })

function positionPanel() {
  if (!triggerRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  panelStyle.value = {
    top:   `${rect.bottom + window.scrollY + 4}px`,
    left:  `${rect.left  + window.scrollX}px`,
    width: `${rect.width}px`,
  }
}

async function toggleOpen() {
  if (props.disabled || props.loading) return
  if (!open.value) {
    open.value = true
    filterText.value = ''
    await nextTick()
    positionPanel()
  } else {
    open.value = false
  }
}

function closePanel() {
  open.value = false
}

// Close on outside click
function onDocClick(e) {
  if (!open.value) return
  const inTrigger = triggerRef.value?.contains(e.target)
  const inPanel   = panelRef.value?.contains(e.target)
  if (!inTrigger && !inPanel) closePanel()
}

// Close on scroll (re-position instead if we're inside a scrollable parent)
function onScroll() {
  if (!open.value) return
  positionPanel()
}

onMounted(() => {
  document.addEventListener('mousedown', onDocClick, true)
  window.addEventListener('scroll', onScroll, true)
  window.addEventListener('resize', onScroll)
})
onUnmounted(() => {
  document.removeEventListener('mousedown', onDocClick, true)
  window.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', onScroll)
})

// Search box is opt-in via `filter`, and also switches on automatically once
// there are enough options that scanning them by eye stops being practical.
const showFilter = computed(() => props.filter || props.options.length > 5)

// ── filtered list ─────────────────────────────────────────────────────────────
const filteredOptions = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((o) => getLabel(o).toLowerCase().includes(q))
})

// ── select actions ────────────────────────────────────────────────────────────
function selectOption(opt) {
  const v = getValue(opt)
  if (props.multiple) {
    const current = Array.isArray(props.modelValue) ? [...props.modelValue] : []
    const idx = current.findIndex((sel) => sameValue(sel, v))
    if (idx >= 0) {
      current.splice(idx, 1)
    } else {
      current.push(v)
    }
    emit('update:modelValue', current)
  } else {
    emit('update:modelValue', v)
    closePanel()
  }
}

function toggleAll() {
  if (!props.multiple) return
  if (allSelected.value) {
    emit('update:modelValue', [])
  } else {
    emit('update:modelValue', props.options.map(getValue))
  }
}

function clearValue(e) {
  e.stopPropagation()
  emit('update:modelValue', props.multiple ? [] : null)
}
</script>

<template>
  <div
    class="ey-select"
    :class="{
      'is-open': open,
      'is-disabled': disabled || loading,
      'has-value': computedTriggerLabel != null,
    }"
  >
    <!-- Trigger -->
    <button
      ref="triggerRef"
      type="button"
      class="ey-select-trigger"
      :disabled="disabled || loading"
      @click="toggleOpen"
    >
      <span class="ey-select-label" :class="{ 'is-placeholder': !computedTriggerLabel && !$slots.value }">
        <slot name="value" :value="modelValue" :option="options.find(o => sameValue(getValue(o), modelValue))">
          {{ computedTriggerLabel ?? placeholder }}
        </slot>
      </span>
      <span v-if="loading" class="ey-select-spinner pi pi-spin pi-spinner" />
      <span
        v-else-if="showClear && computedTriggerLabel != null"
        class="ey-select-clear pi pi-times"
        @click="clearValue"
      />
      <span class="ey-select-caret pi" :class="open ? 'pi-chevron-up' : 'pi-chevron-down'" />
    </button>

    <!-- Overlay panel (teleported so it escapes overflow parents) -->
    <Teleport to="body">
      <Transition name="ey-select-fade">
        <div
          v-if="open"
          ref="panelRef"
          class="ey-select-panel"
          :style="panelStyle"
        >
          <!-- Filter input -->
          <div v-if="showFilter" class="ey-select-filter-wrap">
            <i class="pi pi-search ey-select-filter-icon" />
            <input
              v-model="filterText"
              type="text"
              class="ey-select-filter-input"
              placeholder="Search…"
              @click.stop
            />
          </div>

          <div class="ey-select-list">
            <!-- Select all row (multi only) -->
            <button
              v-if="multiple && showToggleAll && !filterText"
              type="button"
              class="ey-select-item ey-select-item--toggle-all"
              @click.stop="toggleAll"
            >
              <span class="ey-cb" :class="{ 'is-checked': allSelected }">
                <i v-if="allSelected" class="pi pi-check ey-cb-icon" />
              </span>
              <span class="ey-select-item-label font-weight-bold">Select all</span>
              <span class="ey-select-count">{{ selectedCount }}/{{ options.length }}</span>
            </button>
            <div v-if="multiple && showToggleAll && !filterText" class="ey-select-divider" />

            <!-- Options -->
            <button
              v-for="opt in filteredOptions"
              :key="getLabel(opt)"
              type="button"
              class="ey-select-item"
              :class="{ 'is-selected': isSelected(opt) && !multiple }"
              @click.stop="selectOption(opt)"
            >
              <span v-if="multiple" class="ey-cb" :class="{ 'is-checked': isSelected(opt) }">
                <i v-if="isSelected(opt)" class="pi pi-check ey-cb-icon" />
              </span>
              <span class="ey-select-item-label"><slot name="option" :option="opt">{{ getLabel(opt) }}</slot></span>
            </button>

            <div v-if="filteredOptions.length === 0" class="ey-select-empty">No results</div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<!--
  Not scoped — the panel is teleported outside the component's DOM subtree,
  so scoped selectors can't reach it. All rules are namespaced under .ey-select*.
-->
<style>
/* ── Trigger ──────────────────────────────────────────────────────────────── */
.ey-select { display: block; position: relative; }

.ey-select-trigger {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 38px;
  padding: 0 10px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border-input);
  border-radius: 2px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, box-shadow 0.15s;
  gap: 6px;
  color: var(--text-color);
  font-size: 13px;
}
.ey-select-trigger:hover:not(:disabled) {
  border-color: var(--text-color-muted);
}
.ey-select.is-open .ey-select-trigger {
  border-color: var(--ink);
  box-shadow: 0 0 0 2px rgba(26, 26, 36, 0.12);
}
.ey-select-trigger:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: var(--surface-ground);
}

.ey-select-label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  color: var(--text-color);
}
.ey-select-label.is-placeholder {
  color: var(--text-color-muted-2);
}
.ey-select-caret {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-color-muted);
  transition: transform 0.15s;
}
.ey-select.is-open .ey-select-caret {
  color: var(--ink);
}
.ey-select-clear {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-color-muted-2);
  padding: 2px;
  border-radius: 2px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}
.ey-select-clear:hover {
  color: var(--ink);
  background: var(--surface-hover);
}
.ey-select-spinner {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-color-muted);
}

/* ── Panel ────────────────────────────────────────────────────────────────── */
.ey-select-panel {
  position: absolute;
  z-index: 9999;
  background: var(--surface-overlay, #ffffff);
  border: 1px solid var(--ink);
  border-radius: 2px;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.13);
  overflow: hidden;
  min-width: 160px;
}

.ey-select-filter-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 6px;
  border-bottom: 1px solid var(--surface-border-row);
}
.ey-select-filter-icon {
  font-size: 11px;
  color: var(--text-color-muted);
  flex-shrink: 0;
}
.ey-select-filter-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 12.5px;
  color: var(--text-color);
}
.ey-select-filter-input::placeholder {
  color: var(--text-color-muted-2);
}

.ey-select-list {
  max-height: 280px;
  overflow-y: auto;
  overscroll-behavior: contain;
  /* custom thin scrollbar */
  scrollbar-width: thin;
  scrollbar-color: var(--surface-300, #ccc) transparent;
}
.ey-select-list::-webkit-scrollbar { width: 6px; }
.ey-select-list::-webkit-scrollbar-thumb { background: var(--surface-300, #ccc); border-radius: 3px; }

/* ── Items ────────────────────────────────────────────────────────────────── */
.ey-select-item {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 10px;
  padding: 9px 14px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: background 0.1s;
  font-size: 13px;
  color: var(--text-color);
}
.ey-select-item:hover {
  background: var(--surface-hover);
}
.ey-select-item.is-selected {
  background: var(--surface-inset);
  font-weight: 600;
}
.ey-select-item--toggle-all {
  font-weight: 700;
  font-size: 13px;
}

.ey-select-item-label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ey-select-count {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-color-muted);
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

/* ── Checkbox ─────────────────────────────────────────────────────────────── */
.ey-cb {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border: 1.5px solid var(--surface-border-input);
  border-radius: 2px;
  background: #fff;
  transition: background 0.12s, border-color 0.12s;
}
.ey-cb.is-checked {
  background: var(--yellow, #FFE600);
  border-color: var(--yellow, #FFE600);
}
.ey-cb-icon {
  font-size: 9px;
  color: var(--ink, #1A1A24);
  font-weight: 900;
}

/* ── Separator & Empty ───────────────────────────────────────────────────── */
.ey-select-divider {
  height: 1px;
  background: var(--ink);
  margin: 0;
}
.ey-select-empty {
  padding: 12px 14px;
  font-size: 12.5px;
  color: var(--text-color-muted-2);
  text-align: center;
}

/* ── Transition ───────────────────────────────────────────────────────────── */
.ey-select-fade-enter-active,
.ey-select-fade-leave-active {
  transition: opacity 0.12s, transform 0.12s;
}
.ey-select-fade-enter-from,
.ey-select-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
