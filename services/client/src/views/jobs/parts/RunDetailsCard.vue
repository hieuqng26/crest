<script setup>
defineProps({
  // [{ k: 'Job ID', v: '...', mono: true }]
  rows: { type: Array, required: true },
  progress: { type: Number, default: 0 },
  status: { type: String, default: 'queued' },
  errorMessage: { type: String, default: null },
  labelWidth: { type: Number, default: 95 }
})
</script>

<template>
  <div class="run-details card--emphasis">
    <div class="eyebrow">RUN DETAILS</div>
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
  </div>
</template>

<style scoped>
.run-details {
  padding: 14px 16px 6px;
}
.detail-row {
  display: flex;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid #F0F0F3;
  font-size: 12.5px;
}
.detail-key { flex: none; color: var(--text-color-muted); }
.detail-value { flex: 1; line-height: 1.5; word-break: break-word; }

.progress-block { padding: 10px 0 8px; }
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
