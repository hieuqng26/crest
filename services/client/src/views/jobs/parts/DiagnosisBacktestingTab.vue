<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import { cssVar } from '@/utils/chartTheme'
import LinePlot from '@/components/charts/LinePlot.vue'
import DistPlot from '@/components/charts/DistPlot.vue'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import RetrainingBanner from '@/components/ui/RetrainingBanner.vue'
import FilterField from '@/components/ui/FilterField.vue'
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

// The per-observation val_obs arrays are stripped from the segment LIST (they made
// it multi-MB); fetch them for just the selected segment when its backtest scatter
// is shown. getDiagnostics(run, segKey) returns the full metrics incl. val_obs.
const activeSegmentObs = ref(null)
watch(selectedSegmentKey, async (segKey) => {
  activeSegmentObs.value = null
  if (!segKey || !cal.value) return
  try {
    const { data } = await calibrationsAPI.getDiagnostics(cal.value.run_id, segKey)
    activeSegmentObs.value = data.metrics?.val_obs ?? null
  } catch {
    activeSegmentObs.value = null // scatter is best-effort
  }
})

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

// A segment re-run keeps the parent run at "success"; the count is the only
// signal that the metrics below still reflect the previous model. When the
// retrain lands (count returns to 0) reload the segments to pick up the fresh
// metrics — the parent WorkflowDetail poll keeps `targets` (and the count) live.
const retrainingCount = computed(() => cal.value?.retraining_segment_count ?? 0)
watch(retrainingCount, (now, was) => { if (was > 0 && now === 0) loadSegmentsForTarget() })

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

// Full residuals array — binning/KDE now happen client-side inside DistPlot.
const residualValues = computed(() => diag.value?.residuals ?? [])

// ── Backtest chart (actual vs predicted line, single run/segment only) ──────
const backtestPairs = computed(() => {
  let actual, predicted
  if (isSegmented.value) {
    if (!selectedSegmentKey.value || !activeSegmentObs.value) return []
    actual = activeSegmentObs.value.actual ?? []
    predicted = activeSegmentObs.value.predicted ?? []
  } else {
    actual = forecastActual.value
    predicted = forecastPredicted.value
  }
  const pairs = actual.map((a, i) => ({ a, p: predicted[i] })).filter(({ a, p }) => a != null && p != null)
  return pairs.sort((x, y) => x.a - y.a)
})
// Two lines — observations sorted by actual value, indexed on the x axis.
const backtestSeries = computed(() => {
  const pairs = backtestPairs.value
  const x = pairs.map((_, i) => i)
  return [
    { name: 'Actual', x, y: pairs.map((d) => d.a), color: cssVar('--ink-2'), width: 1.6 },
    { name: 'Predicted', x, y: pairs.map((d) => d.p), color: cssVar('--yellow-chart'), width: 2.4 },
  ]
})

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
    <div class="filter-row">
      <FilterField label="Target">
        <EySelect v-model="selectedTargetCol" :options="targets.map(t => ({ label: t.target_col, value: t.target_col }))" optionLabel="label" optionValue="value" class="font-mono" />
      </FilterField>
      <FilterField v-if="isSegmented" label="Sector">
        <EySelect v-model="selectedSector" :options="sectorOptions" optionLabel="label" optionValue="value" :disabled="loadingSegments" />
      </FilterField>
      <FilterField v-if="isSegmented && selectedSector" label="Segment">
        <EySelect v-model="selectedSegmentKey" :options="segmentOptions" optionLabel="label" optionValue="value" class="font-mono" />
      </FilterField>
    </div>

    <RetrainingBanner v-if="retrainingCount > 0">
      {{ retrainingCount }} segment{{ retrainingCount > 1 ? 's are' : ' is' }} re-training — the diagnosis below reflects the previous model{{ retrainingCount > 1 ? 's' : '' }} and will refresh when it completes.
    </RetrainingBanner>

    <div v-if="loadingSegments" class="loading-line"><i class="pi pi-spin pi-spinner" /> Loading segments…</div>

    <template v-else-if="diag">
      <div class="metric-grid">
        <div v-for="m in metricCards" :key="m.label" class="card--emphasis metric-card">
          <div class="font-mono metric-value">{{ m.value }}</div>
          <div class="eyebrow metric-label">{{ m.label }}</div>
        </div>
      </div>

      <div class="chart-grid">
        <div v-if="isRegression && residualValues.length" class="panel chart-card">
          <div class="chart-title">Residual distribution</div>
          <DistPlot
            :values="residualValues"
            name="Residuals"
            :height="280"
            png-filename="residual-distribution"
          />
        </div>

        <div v-if="canShowSinglePredictions && backtestPairs.length > 1" class="panel chart-card">
          <div class="chart-title">Backtesting — Actual vs Predicted</div>
          <LinePlot
            :series="backtestSeries"
            :height="280"
            curve="linear"
            png-filename="backtest-actual-vs-predicted"
          />
        </div>
        <div v-else-if="!canShowSinglePredictions" class="panel">
          <EmptyState icon="pi pi-th-large">Select a specific segment above to view its backtesting chart and predictions.</EmptyState>
        </div>
      </div>

      <div v-if="canShowSinglePredictions" class="panel results-panel">
        <CommonDataTable
          v-if="predictionColumns.length"
          :key="predictionsKey"
          card
          title="Backtest predictions"
          :columns="predictionColumns"
          :fetch-page="predictionsFetchPage"
          :fetch-distinct="predictionsFetchDistinct"
          empty-message="No predictions available."
        />
      </div>
    </template>

    <div v-else class="panel">
      <EmptyState icon="pi pi-chart-bar">No diagnostic data available for this target.</EmptyState>
    </div>

    <a v-if="cal" class="diagnostics-link" @click="router.push({ name: 'jobs_detail', params: { kind: 'training', run_id: cal.run_id } })">
      View full training job &rarr;
    </a>
  </div>
</template>

<style scoped>
.diag-tab { display: flex; flex-direction: column; gap: 16px; }

.filter-row { display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; }

.loading-line { padding: 20px; text-align: center; color: var(--text-color-muted); font-size: 13px; }

/* .panel is global (_brand.scss). */

.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.metric-card { padding: 14px 16px; }
.metric-value { font-size: 24px; font-weight: 600; }
.metric-label { margin-top: 6px; }

/* Residual + backtest plots side by side, each half the section; collapses
 * to one per row once a column would drop below ~360px. */
.chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }

.chart-card { padding: 18px 20px; }
.chart-title { font-size: 13.5px; font-weight: 700; margin-bottom: 14px; }
.results-panel { overflow: hidden; }

.diagnostics-link { display: inline-block; font-size: 12.5px; font-weight: 600; color: var(--text-color-secondary); cursor: pointer; border-bottom: 2px solid var(--yellow); padding-bottom: 1px; width: fit-content; }
.diagnostics-link:hover { color: var(--ink); }
</style>
