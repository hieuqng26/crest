<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  rows:         { type: Array,   required: true },
  progress:     { type: Number,  default: 0 },
  status:       { type: String,  default: 'queued' },
  errorMessage: { type: String,  default: null },
  labelWidth:   { type: Number,  default: 95 },
  collapsible:  { type: Boolean, default: false },
  // Bare mode: render only the rows + progress (no card chrome, no own header
  // or collapse toggle). Used when embedded inside the combined run/log box,
  // which owns the surrounding frame and collapse behaviour.
  bare:         { type: Boolean, default: false },
})

const isLive = (s) => s === 'running' || s === 'queued'

// Start collapsed when the job is already done on mount; expand while live.
const collapsed = ref(props.collapsible && !isLive(props.status))

watch(() => props.status, (s) => {
  if (!props.collapsible) return
  if (isLive(s)) collapsed.value = false
  else collapsed.value = true
})
</script>

<template>
  <!-- Bare: just the content, framed by the parent box -->
  <div v-if="bare" class="run-details-bare">
    <span class="eyebrow">RUN DETAILS</span>
    <div class="detail-list">
      <div v-for="row in rows" :key="row.k" class="detail-row">
        <div class="detail-key" :style="{ width: labelWidth + 'px' }">{{ row.k }}</div>
        <div class="detail-value" :class="{ 'font-mono': row.mono }">{{ row.v }}</div>
      </div>
    </div>

    <div class="progress-block">
      <div class="progress-head">
        <span class="progress-label">Progress</span>
        <span class="font-mono progress-pct">{{ progress }}%</span>
      </div>
      <div class="progress-track">
        <div
          class="progress-fill"
          :class="{ 'is-failed': status === 'failed' }"
          :style="{ width: progress + '%' }"
        />
      </div>
      <div v-if="errorMessage" class="error-box">{{ errorMessage }}</div>
    </div>
  </div>

  <div v-else class="run-details card--emphasis">
    <div
      class="run-details-header"
      :class="{ 'is-clickable': collapsible }"
      @click="collapsible && (collapsed = !collapsed)"
    >
      <span class="eyebrow">RUN DETAILS</span>
      <i v-if="collapsible" class="pi toggle-icon" :class="collapsed ? 'pi-chevron-down' : 'pi-chevron-up'" />
    </div>

    <template v-if="!collapsed">
      <div v-for="row in rows" :key="row.k" class="detail-row">
        <div class="detail-key" :style="{ width: labelWidth + 'px' }">{{ row.k }}</div>
        <div class="detail-value" :class="{ 'font-mono': row.mono }">{{ row.v }}</div>
      </div>

      <div class="progress-block">
        <div class="progress-head">
          <span class="progress-label">Progress</span>
          <span class="font-mono progress-pct">{{ progress }}%</span>
        </div>
        <div class="progress-track">
          <div
            class="progress-fill"
            :class="{ 'is-failed': status === 'failed' }"
            :style="{ width: progress + '%' }"
          />
        </div>
        <div v-if="errorMessage" class="error-box">{{ errorMessage }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.run-details { padding: 0; }

/* Bare mode: content only, framed by the parent combined box. */
.run-details-bare {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 14px 16px;
}
.run-details-bare .eyebrow { margin-bottom: 10px; }
.run-details-bare .detail-row { padding-left: 0; padding-right: 0; }
.run-details-bare .progress-block { padding: 12px 0 0; }

.run-details-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 10px;
}
.run-details-header.is-clickable { cursor: pointer; user-select: none; }
.run-details-header.is-clickable:hover { background: var(--surface-hover); }

.toggle-icon { font-size: 11px; color: var(--text-color-muted); }

.detail-row {
  display: flex;
  gap: 10px;
  padding: 6px 16px;
  border-bottom: 1px solid #F0F0F3;
  font-size: 12.5px;
}
.detail-key { flex: none; color: var(--text-color-muted); }
.detail-value { flex: 1; line-height: 1.5; word-break: break-word; }

.progress-block { padding: 10px 16px 14px; }
.progress-head {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  margin-bottom: 6px;
}
.progress-label { color: var(--text-color-muted); font-weight: 600; }
.progress-pct { font-weight: 600; }
.progress-track {
  height: 6px;
  background: var(--surface-border-row);
  border-radius: 1px;
  overflow: hidden;
}
.progress-fill { height: 100%; background: var(--yellow); }
.progress-fill.is-failed { background: var(--error-color); }

.error-box {
  margin-top: 10px;
  font-size: 12px;
  color: var(--error-text-color);
  background: rgba(196, 51, 29, 0.08);
  border: 1px solid rgba(196, 51, 29, 0.2);
  border-radius: 2px;
  padding: 8px 10px;
}
</style>
