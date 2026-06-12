<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import diag from '@/views/evaluate/mock/diagnostics.json'
import { isTimeSeries } from '../runUtils'

const props = defineProps({ run: { type: Object, required: true } })
const router = useRouter()

const meta = [
  { label: 'Config',         value: props.run.config_name },
  { label: 'Algorithm',      value: props.run.algorithm },
  { label: 'Dataset',        value: props.run.dataset_name },
  { label: 'Triggered by',   value: props.run.triggered_by },
  { label: 'Started',        value: props.run.started_at },
  { label: 'Finished',       value: props.run.finished_at ?? '—' },
  { label: 'Feature scaler', value: 'StandardScaler' },
  { label: 'CV search',      value: 'GridSearchCV · 5-fold · roc_auc' },
  { label: 'Train / Val',    value: '80% / 20%' }
]

const kpis = computed(() => {
  if (props.run.status !== 'success') return []
  return [
    { label: 'AUC-ROC',  value: diag.metrics.auc_roc },
    { label: 'KS',       value: diag.metrics.ks },
    { label: 'Gini',     value: diag.metrics.gini },
    { label: 'Accuracy', value: diag.metrics.accuracy },
    { label: 'F1',       value: diag.metrics.f1 }
  ]
})

const rocSpark = computed(() => ({
  labels: diag.roc_curve.fpr.map(v => v.toFixed(2)),
  datasets: [
    { label: 'ROC', data: diag.roc_curve.tpr, borderColor: '#60a5fa', backgroundColor: 'rgba(96,165,250,0.15)', fill: true, tension: 0.3, pointRadius: 0 },
    { label: 'Random', data: diag.roc_curve.fpr, borderColor: '#6b7280', borderDash: [4, 4], pointRadius: 0, fill: false }
  ]
}))
const sparkOptions = {
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { ticks: { color: '#9ca3af', maxTicksLimit: 4 }, grid: { display: false } },
    y: { ticks: { color: '#9ca3af', maxTicksLimit: 4 }, grid: { color: 'rgba(156,163,175,0.1)' } }
  }
}
</script>

<template>
  <div class="flex flex-column gap-4">
    <!-- Meta grid -->
    <div class="surface-card border-round shadow-1 p-4">
      <h4 class="text-sm font-semibold text-color-secondary uppercase m-0 mb-3">Run details</h4>
      <div class="grid m-0 gap-3 grid-cols-1 md:grid-cols-3">
        <div v-for="m in meta" :key="m.label" class="flex flex-column">
          <span class="text-xs text-color-secondary uppercase">{{ m.label }}</span>
          <span class="text-sm font-medium font-mono">{{ m.value }}</span>
        </div>
      </div>
    </div>

    <!-- KPI strip (success only) -->
    <div v-if="kpis.length" class="surface-card border-round shadow-1 p-4">
      <h4 class="text-sm font-semibold text-color-secondary uppercase m-0 mb-3">Final metrics</h4>
      <div class="flex flex-wrap gap-3">
        <div v-for="k in kpis" :key="k.label" class="surface-ground border-round px-4 py-3 text-center min-w-6rem">
          <div class="text-xl font-bold text-blue-400">{{ k.value.toFixed(3) }}</div>
          <div class="text-xs text-color-secondary mt-1">{{ k.label }}</div>
        </div>
      </div>
    </div>

    <!-- Quick links -->
    <div v-if="run.status === 'success'" class="surface-card border-round shadow-1 p-4">
      <div class="flex align-items-center justify-content-between mb-3">
        <h4 class="text-sm font-semibold text-color-secondary uppercase m-0">ROC preview</h4>
        <div class="flex gap-2">
          <Button label="Diagnostics" icon="pi pi-chart-bar"  size="small" text
            @click="router.replace({ query: { tab: 'diagnostics' } })" />
          <Button v-if="isTimeSeries(run.algorithm)" label="Forecast" icon="pi pi-chart-line" size="small" text
            @click="router.replace({ query: { tab: 'forecast' } })" />
        </div>
      </div>
      <div style="height: 160px">
        <Chart type="line" :data="rocSpark" :options="sparkOptions" class="h-full" />
      </div>
    </div>
  </div>
</template>
