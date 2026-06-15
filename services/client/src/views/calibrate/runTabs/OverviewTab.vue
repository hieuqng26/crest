<script setup>
import { computed } from 'vue'
import { fmtDate } from '@/utils/datetime'

const props = defineProps({ run: { type: Object, required: true } })

const fmtNum = (v) => {
  if (typeof v !== 'number') return String(v ?? '—')
  return Math.abs(v) < 1 ? v.toFixed(4) : v.toLocaleString(undefined, { maximumFractionDigits: 4 })
}

const valMetrics = computed(() => {
  try { return JSON.parse(props.run.val_metrics_json || 'null') } catch { return null }
})

const trainMetrics = computed(() => {
  try { return JSON.parse(props.run.train_metrics_json || 'null') } catch { return null }
})

const bestParamsData = computed(() => {
  try { return JSON.parse(props.run.best_params_json || 'null') } catch { return null }
})

// Scalar KPI metrics only (exclude nested objects like roc_curve, confusion_matrix)
const scalarMetrics = computed(() => {
  const m = valMetrics.value
  if (!m) return []
  return Object.entries(m)
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: v }))
})

const featureImportance = computed(() => valMetrics.value?.feature_importance ?? [])
const coefTable = computed(() => valMetrics.value?.coef_table ?? [])
const hasFeatureImportance = computed(() => featureImportance.value.length > 0)
const hasCoefTable = computed(() => coefTable.value.length > 0)

const maxAbsCoef = computed(() => Math.max(...coefTable.value.map(f => Math.abs(f.coef)), 1))
const logCoefWidth = (coef) =>
  (Math.log1p(Math.abs(coef)) / Math.log1p(maxAbsCoef.value) * 50).toFixed(1) + '%'

const featureCols = computed(() => {
  try {
    const cols = JSON.parse(props.run.feature_cols_json || '[]')
    return cols.length ? cols.join(', ') : '—'
  } catch { return '—' }
})

const metaRows = computed(() => [
  { label: 'Run ID',         value: props.run.run_id       || '—', mono: true },
  { label: 'Configuration',  value: props.run.config_name  || '—' },
  { label: 'Algorithm',      value: props.run.algorithm    || '—' },
  { label: 'Dataset',        value: props.run.dataset_name || '—' },
  { label: 'Target',         value: props.run.target_col   || '—' },
  { label: 'Features',       value: featureCols.value },
  { label: 'Triggered by',   value: props.run.triggered_by || '—' },
  { label: 'Started',        value: fmtDate(props.run.started_at) },
  { label: 'Finished',       value: fmtDate(props.run.finished_at) },
])
</script>

<template>
  <div class="flex flex-column gap-4">

    <!-- Run info -->
    <div class="surface-card border-round shadow-1" style="padding: 0">
      <div class="px-4 pt-4 pb-2">
        <span class="text-xs font-semibold uppercase text-color-secondary" style="letter-spacing: 0.06em">Run details</span>
      </div>
      <div class="flex flex-wrap" style="gap: 0">
        <div
          v-for="m in metaRows" :key="m.label"
          class="flex flex-column p-4"
          :style="[
            'border-top: 1px solid var(--surface-border)',
            m.label === 'Features' || m.label === 'Run ID' ? 'min-width: 100%; flex: 1 1 100%' : 'min-width: 12rem; flex: 1'
          ]"
        >
          <span class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">{{ m.label }}</span>
          <span class="font-medium text-sm" :class="{ 'font-mono': m.mono }">{{ m.value }}</span>
        </div>
      </div>
    </div>

    <!-- KPI metrics strip -->
    <div v-if="scalarMetrics.length" class="surface-card border-round shadow-1" style="padding: 0">
      <div class="px-4 pt-4 pb-2">
        <span class="text-xs font-semibold uppercase text-color-secondary" style="letter-spacing: 0.06em">Validation metrics</span>
      </div>
      <div class="flex flex-wrap" style="gap: 0">
        <div
          v-for="m in scalarMetrics" :key="m.label"
          class="flex flex-column p-4 text-center"
          style="min-width: 8rem; flex: 1; border-top: 1px solid var(--surface-border)"
        >
          <span class="text-xl font-bold text-blue-400">{{ fmtNum(m.value) }}</span>
          <span class="text-xs text-color-secondary mt-1 capitalize">{{ m.label }}</span>
        </div>
      </div>
    </div>

    <!-- Train metrics -->
    <div v-if="trainMetrics && Object.keys(trainMetrics).length" class="surface-card border-round shadow-1" style="padding: 0">
      <div class="px-4 pt-4 pb-2">
        <span class="text-xs font-semibold uppercase text-color-secondary" style="letter-spacing: 0.06em">Train metrics</span>
      </div>
      <div class="flex flex-wrap" style="gap: 0">
        <div
          v-for="[k, v] in Object.entries(trainMetrics).filter(([,v]) => typeof v === 'number')" :key="k"
          class="flex flex-column p-4 text-center"
          style="min-width: 8rem; flex: 1; border-top: 1px solid var(--surface-border)"
        >
          <span class="text-xl font-bold text-green-400">{{ fmtNum(v) }}</span>
          <span class="text-xs text-color-secondary mt-1 capitalize">{{ k.replace(/_/g, ' ') }}</span>
        </div>
      </div>
    </div>

    <!-- Best hyperparameters (CV search) -->
    <div v-if="bestParamsData" class="surface-card border-round shadow-1 p-4">
      <div class="flex align-items-center justify-content-between mb-3">
        <span class="text-xs font-semibold uppercase text-color-secondary" style="letter-spacing: 0.06em">Best hyperparameters</span>
        <Tag v-if="bestParamsData.best_score != null" :value="`Best score: ${Number(bestParamsData.best_score).toFixed(4)}`" severity="info" class="text-xs" />
      </div>
      <div class="flex flex-wrap gap-3">
        <div
          v-for="[k, v] in Object.entries(bestParamsData.best_params || {})" :key="k"
          class="surface-ground border-round px-3 py-2"
        >
          <div class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">{{ k }}</div>
          <div class="font-mono font-semibold text-sm">{{ v }}</div>
        </div>
      </div>
    </div>

    <!-- Feature importance (tree/ensemble models) -->
    <div v-if="hasFeatureImportance" class="surface-card border-round shadow-1 p-4">
      <span class="text-xs font-semibold uppercase text-color-secondary block mb-3" style="letter-spacing: 0.06em">Feature Importance</span>
      <div class="flex flex-column gap-2">
        <div
          v-for="f in [...featureImportance].sort((a, b) => b.importance - a.importance)"
          :key="f.feature"
          class="flex align-items-center gap-3"
        >
          <span class="font-mono text-xs text-color-secondary" style="min-width: 10rem; text-align: right">{{ f.feature }}</span>
          <div class="flex-1 surface-ground border-round overflow-hidden" style="height: 8px">
            <div class="h-full border-round" style="background: #60a5fa; transition: width 400ms ease" :style="{ width: (f.importance * 100).toFixed(1) + '%' }" />
          </div>
          <span class="font-mono text-xs" style="min-width: 4rem">{{ f.importance.toFixed(4) }}</span>
        </div>
      </div>
    </div>

    <!-- Coefficients (linear models: OLS, Lasso, ElasticNet, Ridge) -->
    <div v-if="hasCoefTable" class="surface-card border-round shadow-1 p-4">
      <div class="flex align-items-center justify-content-between mb-3">
        <span class="text-xs font-semibold uppercase text-color-secondary" style="letter-spacing: 0.06em">Coefficients</span>
        <span class="text-xs text-color-secondary" style="font-style: italic">bar widths on log scale</span>
      </div>
      <div class="flex flex-column gap-2">
        <div
          v-for="f in [...coefTable].sort((a, b) => Math.abs(b.coef) - Math.abs(a.coef))"
          :key="f.feature"
          class="flex align-items-center gap-3"
        >
          <span class="font-mono text-xs text-color-secondary" style="min-width: 10rem; text-align: right">{{ f.feature }}</span>
          <!-- centre-anchored bar: negative goes left, positive goes right -->
          <div class="flex-1 flex align-items-center" style="height: 8px; position: relative">
            <div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:var(--surface-400)" />
            <div
              style="position:absolute;height:100%;border-radius:2px;transition:width 400ms ease"
              :style="{
                width: logCoefWidth(f.coef),
                left:  f.coef >= 0 ? '50%' : undefined,
                right: f.coef <  0 ? '50%' : undefined,
                background: f.coef >= 0 ? '#34d399' : '#f87171',
              }"
            />
          </div>
          <span
            class="font-mono text-xs"
            style="min-width: 5rem; text-align: right"
            :style="{ color: f.coef >= 0 ? '#34d399' : '#f87171' }"
          >{{ f.coef >= 0 ? '+' : '' }}{{ f.coef.toFixed(4) }}</span>
        </div>
      </div>
    </div>

    <!-- Pending / failed state -->
    <div v-if="run.status !== 'success'" class="surface-card border-round shadow-1 p-5 text-center text-color-secondary">
      <i v-if="run.status === 'running' || run.status === 'queued'" class="pi pi-spin pi-spinner text-2xl block mb-2" />
      <i v-else class="pi pi-times-circle text-2xl block mb-2 text-red-400" />
      <p class="m-0 text-sm">
        <template v-if="run.status === 'running' || run.status === 'queued'">Run in progress — metrics will appear here once complete.</template>
        <template v-else-if="run.status === 'failed'">Run failed. Check the Progress tab for error details.</template>
      </p>
    </div>

  </div>
</template>
