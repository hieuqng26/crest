<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import { probeColumns } from './resultColumns.js'

const props = defineProps({
  targets: { type: Array, required: true } // [{ target_col, calibration }]
})

const router = useRouter()
const toast = useToast()

const parseJson = (s, fallback = null) => { try { return s ? JSON.parse(s) : fallback } catch { return fallback } }

// ── Target → sector → segment cascade ────────────────────────────────────────
const selectedTargetCol = ref(props.targets[0]?.target_col ?? null)
const selectedTarget = computed(() => props.targets.find((t) => t.target_col === selectedTargetCol.value) || null)
const cal = computed(() => selectedTarget.value?.calibration ?? null)
const isSegmented = computed(() => !!cal.value?.is_segmented)

const segments = ref([])
const loadingSegments = ref(false)
const selectedSector = ref(null) // null = "all sectors (aggregate)"
const selectedSegmentKey = ref(null)

const sectorOptions = computed(() => {
  const uniq = [...new Set(segments.value.map((s) => s.sector))]
  return [{ label: 'All sectors (aggregate)', value: null }, ...uniq.map((s) => ({ label: s, value: s }))]
})
const segmentOptions = computed(() =>
  segments.value.filter((s) => s.sector === selectedSector.value).map((s) => ({ label: s.split_value, value: s.segment_key }))
)
const activeSegment = computed(() => segments.value.find((s) => s.segment_key === selectedSegmentKey.value) || null)

const loadSegmentsForTarget = async () => {
  segments.value = []
  selectedSector.value = null
  selectedSegmentKey.value = null
  if (!cal.value || !isSegmented.value) return
  loadingSegments.value = true
  try {
    const { data } = await calibrationsAPI.segments(cal.value.run_id)
    segments.value = (data.segments ?? []).filter((s) => s.status === 'success')
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load segments', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loadingSegments.value = false
  }
}
watch(selectedTargetCol, loadSegmentsForTarget)
onMounted(loadSegmentsForTarget)

watch(selectedSector, (sector) => {
  selectedSegmentKey.value = sector ? (segmentOptions.value[0]?.value ?? null) : null
})

// ── Diagnostics (aggregate weighted-mean across segments, or one segment/run) ─
const forecastActual = ref([])
const forecastPredicted = ref([])
const loadingForecast = ref(false)

const loadNonSegmentedForecast = async () => {
  forecastActual.value = []
  forecastPredicted.value = []
  if (!cal.value) return
  loadingForecast.value = true
  try {
    const { data } = await calibrationsAPI.forecast(cal.value.run_id)
    if (data.length > 0) {
      forecastActual.value = data[0].forecast_json?.actual ?? []
      forecastPredicted.value = data[0].forecast_json?.predicted ?? []
    }
  } catch {
    // backtesting is best-effort; metric cards still work off val_metrics
  } finally {
    loadingForecast.value = false
  }
}
watch(() => cal.value?.run_id, () => { if (!isSegmented.value) loadNonSegmentedForecast() }, { immediate: true })

const diag = computed(() => {
  if (!cal.value) return null
  if (!isSegmented.value) return parseJson(cal.value.val_metrics_json)
  if (selectedSegmentKey.value && activeSegment.value) return activeSegment.value.val_metrics
  const pool = selectedSector.value ? segments.value.filter((s) => s.sector === selectedSector.value) : segments.value
  if (!pool.length) return null
  let wSum = 0, r2Sum = 0, rmseSum = 0, maeSum = 0, haveMae = true
  const residuals = []
  for (const s of pool) {
    const w = s.row_count || 1
    const vm = s.val_metrics || {}
    wSum += w
    r2Sum += (vm.r2 ?? 0) * w
    rmseSum += (vm.rmse ?? 0) * w
    if (typeof vm.mae === 'number') maeSum += vm.mae * w
    else haveMae = false
    if (Array.isArray(vm.residuals)) residuals.push(...vm.residuals)
  }
  if (!wSum) return null
  return {
    r2: r2Sum / wSum,
    rmse: rmseSum / wSum,
    mae: haveMae ? maeSum / wSum : undefined,
    residuals: residuals.length ? residuals : undefined
  }
})
const isRegression = computed(() => Array.isArray(diag.value?.residuals))

const metricCards = computed(() => {
  const d = diag.value
  if (!d) return []
  if (isRegression.value) {
    const maxErr = d.residuals?.length ? Math.max(...d.residuals.map(Math.abs)) : null
    return [
      { label: 'R²', value: typeof d.r2 === 'number' ? d.r2.toFixed(4) : '—' },
      { label: 'MAE', value: typeof d.mae === 'number' ? d.mae.toFixed(4) : '—' },
      { label: 'RMSE', value: typeof d.rmse === 'number' ? d.rmse.toFixed(4) : '—' },
      { label: 'MAX |ERR|', value: maxErr != null ? maxErr.toFixed(4) : '—' }
    ]
  }
  const KEYS = ['auc_roc', 'ks', 'gini', 'accuracy', 'precision', 'recall', 'f1']
  return KEYS.filter((k) => typeof d[k] === 'number').slice(0, 4)
    .map((k) => ({ label: k.replace(/_/g, ' ').toUpperCase(), value: d[k].toFixed(4) }))
})

const residHist = computed(() => {
  const residuals = diag.value?.residuals
  if (!residuals?.length) return null
  const N_BINS = 16
  const min = Math.min(...residuals), max = Math.max(...residuals)
  const width = (max - min) / N_BINS || 1
  const counts = new Array(N_BINS).fill(0)
  residuals.forEach((r) => { counts[Math.min(Math.floor((r - min) / width), N_BINS - 1)]++ })
  const modalIdx = counts.indexOf(Math.max(...counts))
  const maxCount = Math.max(...counts) || 1
  return counts.map((c, i) => ({ pct: (c / maxCount) * 100, isModal: i === modalIdx }))
})

// ── Backtest chart (actual vs predicted line, single run/segment only) ──────
const backtestPairs = computed(() => {
  let actual, predicted
  if (isSegmented.value) {
    if (!selectedSegmentKey.value || !activeSegment.value?.val_metrics?.val_obs) return []
    actual = activeSegment.value.val_metrics.val_obs.actual ?? []
    predicted = activeSegment.value.val_metrics.val_obs.predicted ?? []
  } else {
    actual = forecastActual.value
    predicted = forecastPredicted.value
  }
  const pairs = actual.map((a, i) => ({ a, p: predicted[i] })).filter(({ a, p }) => a != null && p != null)
  return pairs.sort((x, y) => x.a - y.a)
})
const backtestPath = (key) => {
  const pairs = backtestPairs.value
  if (pairs.length < 2) return ''
  const values = pairs.map((d) => d[key])
  const min = Math.min(...values), max = Math.max(...values)
  const range = max - min || 1
  const W = 600, H = 160
  return pairs
    .map((d, i) => {
      const x = (i / (pairs.length - 1)) * W
      const y = H - ((d[key] - min) / range) * H
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

// ── Paginated backtest predictions table (single run/segment only) ──────────
const canShowSinglePredictions = computed(() => !isSegmented.value || !!selectedSegmentKey.value)
const predictionColumns = ref([])
const predictionsKey = computed(() => `${cal.value?.run_id ?? ''}::${selectedSegmentKey.value ?? ''}`)

const predictionsFetchPage = (params) =>
  isSegmented.value
    ? calibrationsAPI.segmentBacktestPredictions(cal.value.run_id, selectedSegmentKey.value, params)
    : calibrationsAPI.backtestPredictions(cal.value.run_id, params)
const predictionsFetchDistinct = (column) =>
  isSegmented.value
    ? calibrationsAPI.segmentBacktestPredictionsDistinct(cal.value.run_id, selectedSegmentKey.value, column)
    : calibrationsAPI.backtestPredictionsDistinct(cal.value.run_id, column)

watch([predictionsKey, canShowSinglePredictions], async () => {
  predictionColumns.value = []
  if (!cal.value || !canShowSinglePredictions.value) return
  predictionColumns.value = await probeColumns(predictionsFetchPage)
}, { immediate: true })
</script>

<template>
  <div class="diag-tab">
    <div class="filter-bar">
      <div class="filter-col">
        <label class="field-label">Target</label>
        <Dropdown v-model="selectedTargetCol" :options="targets.map(t => ({ label: t.target_col, value: t.target_col }))" optionLabel="label" optionValue="value" class="w-full font-mono" />
      </div>
      <div v-if="isSegmented" class="filter-col">
        <label class="field-label">Sector</label>
        <Dropdown v-model="selectedSector" :options="sectorOptions" optionLabel="label" optionValue="value" class="w-full" :disabled="loadingSegments" />
      </div>
      <div v-if="isSegmented && selectedSector" class="filter-col">
        <label class="field-label">Segment</label>
        <Dropdown v-model="selectedSegmentKey" :options="segmentOptions" optionLabel="label" optionValue="value" class="w-full font-mono" />
      </div>
    </div>

    <div v-if="loadingSegments" class="loading-line"><i class="pi pi-spin pi-spinner" /> Loading segments…</div>

    <template v-else-if="diag">
      <div class="metric-grid">
        <div v-for="m in metricCards" :key="m.label" class="card--emphasis metric-card">
          <div class="font-mono metric-value">{{ m.value }}</div>
          <div class="eyebrow metric-label">{{ m.label }}</div>
        </div>
      </div>

      <div v-if="isRegression && residHist" class="panel chart-card">
        <div class="chart-title">Residual distribution</div>
        <div class="hist-wrap">
          <div v-for="(b, i) in residHist" :key="i" class="hist-bar" :class="{ 'is-modal': b.isModal }" :style="{ height: Math.max(b.pct, 2) + '%' }" />
        </div>
        <div class="hist-zero" />
      </div>

      <div v-if="canShowSinglePredictions && backtestPairs.length > 1" class="panel chart-card">
        <div class="chart-title">Backtesting — Actual vs Predicted</div>
        <svg viewBox="0 0 600 160" class="backtest-svg" preserveAspectRatio="none">
          <line v-for="i in 4" :key="i" :y1="i * 32" :y2="i * 32" x1="0" x2="600" class="gridline" />
          <path :d="backtestPath('a')" class="line-actual" />
          <path :d="backtestPath('p')" class="line-predicted" />
        </svg>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-swatch legend-actual" />Actual</span>
          <span class="legend-item"><span class="legend-swatch legend-predicted" />Predicted</span>
        </div>
      </div>
      <div v-else-if="!canShowSinglePredictions" class="panel chart-card empty-note">
        <i class="pi pi-th-large" />
        <p>Select a specific segment above to view its backtesting chart and predictions.</p>
      </div>

      <div v-if="canShowSinglePredictions" class="panel results-panel">
        <div class="chart-title results-title">Backtest predictions</div>
        <CommonDataTable
          v-if="predictionColumns.length"
          :key="predictionsKey"
          :columns="predictionColumns"
          :fetch-page="predictionsFetchPage"
          :fetch-distinct="predictionsFetchDistinct"
          empty-message="No predictions available."
        />
      </div>
    </template>

    <div v-else class="panel chart-card empty-note">
      <i class="pi pi-chart-bar" />
      <p>No diagnostic data available for this target.</p>
    </div>

    <a v-if="cal" class="diagnostics-link" @click="router.push({ name: 'jobs_detail', params: { kind: 'training', run_id: cal.run_id } })">
      View full training job &rarr;
    </a>
  </div>
</template>

<style scoped>
.diag-tab { display: flex; flex-direction: column; gap: 16px; }

.filter-bar { display: flex; gap: 16px; flex-wrap: wrap; background: var(--surface-inset); border-radius: 2px; padding: 14px 16px; }
.filter-col { display: flex; flex-direction: column; gap: 6px; min-width: 200px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }

.loading-line { padding: 20px; text-align: center; color: var(--text-color-muted); font-size: 13px; }

.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; }

.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.metric-card { padding: 14px 16px; }
.metric-value { font-size: 24px; font-weight: 600; }
.metric-label { margin-top: 6px; }

.chart-card { padding: 18px 20px; }
.chart-title { font-size: 13.5px; font-weight: 700; margin-bottom: 14px; }
.results-panel { padding: 18px 20px; overflow: hidden; }
.results-title { margin-bottom: 10px; }

.hist-wrap { display: flex; align-items: flex-end; gap: 3px; height: 120px; }
.hist-bar { flex: 1; background: var(--ink-2); border-radius: 1px 1px 0 0; }
.hist-bar.is-modal { background: var(--yellow); }
.hist-zero { border-top: 1px dashed var(--ink); margin-top: 2px; }

.backtest-svg { width: 100%; height: 160px; display: block; }
.gridline { stroke: #F0F0F3; stroke-width: 1; }
.line-actual { fill: none; stroke: var(--ink-2); stroke-width: 1.4; }
.line-predicted { fill: none; stroke: var(--yellow-chart); stroke-width: 2.6; }
.chart-legend { display: flex; gap: 16px; margin-top: 12px; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-color-secondary); }
.legend-swatch { width: 14px; height: 3px; border-radius: 1px; display: inline-block; }
.legend-actual { background: var(--ink-2); }
.legend-predicted { background: var(--yellow-chart); }

.empty-note { text-align: center; color: var(--text-color-muted); padding: 32px 20px; }
.empty-note i { font-size: 22px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-note p { margin: 0; font-size: 13px; }

.diagnostics-link { display: inline-block; font-size: 12.5px; font-weight: 600; color: var(--text-color-secondary); cursor: pointer; border-bottom: 2px solid var(--yellow); padding-bottom: 1px; width: fit-content; }
.diagnostics-link:hover { color: var(--ink); }
</style>
