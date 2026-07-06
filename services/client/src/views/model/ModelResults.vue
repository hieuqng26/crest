<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import { fmtDate } from '@/utils/datetime'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()
const toast = useToast()

const loading = ref(true)
const runs = ref([])
const selectedRunId = ref(null)

const parseJson = (s, fallback = null) => { try { return s ? JSON.parse(s) : fallback } catch { return fallback } }

const sortedRuns = computed(() =>
  [...runs.value].sort((a, b) => new Date(b.finished_at ?? 0) - new Date(a.finished_at ?? 0))
)
const selectedRun = computed(() => runs.value.find(r => r.run_id === selectedRunId.value) || null)

const rowMetrics = (r) => {
  if (r.is_segmented) return null
  return parseJson(r.val_metrics_json)
}
const rowCaption = (r) => {
  const m = rowMetrics(r)
  if (m && typeof m.r2 === 'number') return `${r.algorithm} · R² ${m.r2.toFixed(4)}`
  if (r.is_segmented) return `${r.algorithm} · ${(r.seg_sectors ?? []).length} sector(s)`
  return r.algorithm ?? '—'
}

// ── Selected model detail ────────────────────────────────────────────────────
const segments = ref([])
const loadingDetail = ref(false)
const forecastActual = ref([])
const forecastPredicted = ref([])

const loadDetail = async (run) => {
  segments.value = []
  forecastActual.value = []
  forecastPredicted.value = []
  if (!run) return
  loadingDetail.value = true
  try {
    if (run.is_segmented) {
      const { data } = await calibrationsAPI.segments(run.run_id)
      segments.value = (data.segments ?? []).filter(s => s.status === 'success')
    } else {
      try {
        const { data } = await calibrationsAPI.forecast(run.run_id)
        if (data.length > 0) {
          forecastActual.value = data[0].forecast_json?.actual ?? []
          forecastPredicted.value = data[0].forecast_json?.predicted ?? []
        }
      } catch {
        // backtesting is best-effort; metric cards still work off val_metrics
      }
    }
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load model detail', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loadingDetail.value = false
  }
}

watch(selectedRun, (run) => loadDetail(run))

// ── Properties ────────────────────────────────────────────────────────────────
const properties = computed(() => {
  const r = selectedRun.value
  if (!r) return []
  const featureCols = parseJson(r.feature_cols_json, [])
  return [
    { k: 'Algorithm', v: r.algorithm ?? '—' },
    { k: 'Mode', v: 'Manual' },
    { k: 'Target', v: r.target_col ?? '—' },
    { k: 'Dataset', v: r.dataset_name ?? '—' },
    { k: 'Split by', v: r.seg_split_by ?? '—' },
    { k: 'Segments', v: r.is_segmented ? `${segments.value.length || (r.seg_sectors ?? []).length}` : 'None' },
    { k: 'Features', v: featureCols.length ? `${featureCols.length} selected` : 'All columns' },
    { k: 'Trained', v: r.finished_at ? fmtDate(r.finished_at) : '—' }
  ]
})

// ── Aggregate diagnostics (segmented = row_count-weighted mean across segments) ──
const diag = computed(() => {
  const r = selectedRun.value
  if (!r) return null
  if (!r.is_segmented) return parseJson(r.val_metrics_json)
  if (!segments.value.length) return null
  let wSum = 0, r2Sum = 0, rmseSum = 0, maeSum = 0, haveMae = true
  const residuals = []
  for (const s of segments.value) {
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
  return KEYS.filter(k => typeof d[k] === 'number').slice(0, 4)
    .map(k => ({ label: k.replace(/_/g, ' ').toUpperCase(), value: d[k].toFixed(4) }))
})

// ── Residual histogram ───────────────────────────────────────────────────────
const residHist = computed(() => {
  const residuals = diag.value?.residuals
  if (!residuals?.length) return null
  const N_BINS = 16
  const min = Math.min(...residuals), max = Math.max(...residuals)
  const width = (max - min) / N_BINS || 1
  const counts = new Array(N_BINS).fill(0)
  residuals.forEach(r => { counts[Math.min(Math.floor((r - min) / width), N_BINS - 1)]++ })
  const modalIdx = counts.indexOf(Math.max(...counts))
  const maxCount = Math.max(...counts) || 1
  return counts.map((c, i) => ({ pct: (c / maxCount) * 100, isModal: i === modalIdx }))
})

// ── Backtest chart geometry (non-segmented only) ─────────────────────────────
const backtestPairs = computed(() => {
  const pairs = forecastActual.value
    .map((a, i) => ({ a, p: forecastPredicted.value[i] }))
    .filter(({ a, p }) => a != null && p != null)
  return pairs.sort((x, y) => x.a - y.a)
})
const backtestPath = (key) => {
  const pairs = backtestPairs.value
  if (pairs.length < 2) return ''
  const values = pairs.map(d => d[key])
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

const selectRun = (r) => { selectedRunId.value = r.run_id }

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await calibrationsAPI.list({ per_page: 200, status: 'success' })
    runs.value = data.items ?? []
    if (sortedRuns.value.length) selectedRunId.value = sortedRuns.value[0].run_id
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load models', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <PageHeader eyebrow="MODEL" title="Model Results" subtitle="Trained models and their validation performance" />

    <div v-if="!loading && runs.length === 0" class="empty-state panel">
      <i class="pi pi-chart-bar" />
      <p>No trained models yet.</p>
      <Button class="btn-cta mt-2" @click="router.push({ name: 'model_new' })">
        <span class="btn-play">&#9654;</span><span>Train a model</span>
      </Button>
    </div>

    <div v-else class="results-grid">
      <!-- Left list -->
      <div class="panel model-list">
        <div class="eyebrow model-list-label">Trained models</div>
        <div
          v-for="r in sortedRuns" :key="r.run_id"
          class="model-row" :class="{ 'is-active': r.run_id === selectedRunId }"
          @click="selectRun(r)"
        >
          <div class="model-row-name">{{ r.run_name ?? r.config_name ?? r.run_id.slice(0, 8) }}</div>
          <div class="font-mono model-row-caption">{{ rowCaption(r) }}</div>
          <div class="font-mono model-row-date">{{ r.finished_at ? fmtDate(r.finished_at) : '—' }}</div>
        </div>
      </div>

      <!-- Right detail -->
      <div v-if="selectedRun" class="detail-col">
        <div class="card--emphasis properties-card">
          <div class="properties-head">
            <span class="font-mono model-name">{{ selectedRun.run_name ?? selectedRun.config_name }}</span>
            <span class="tag-fill">MANUAL</span>
            <span class="tag-outline">{{ selectedRun.algorithm }}</span>
          </div>
          <div v-for="p in properties" :key="p.k" class="prop-row">
            <div class="prop-key">{{ p.k }}</div>
            <div class="font-mono prop-value">{{ p.v }}</div>
          </div>
        </div>

        <div v-if="loadingDetail" class="loading-line"><i class="pi pi-spin pi-spinner" /> Loading results…</div>

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

          <div v-if="!selectedRun.is_segmented && backtestPairs.length > 1" class="panel chart-card">
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

          <div v-else-if="selectedRun.is_segmented" class="panel chart-card empty-note">
            <i class="pi pi-th-large" />
            <p>Per-segment backtesting and diagnostics are in Job Detail.</p>
            <Button label="Open Job Detail" outlined size="small" @click="router.push({ name: 'jobs_detail', params: { kind: 'training', run_id: selectedRun.run_id } })" />
          </div>
        </template>

        <div v-else class="panel chart-card empty-note">
          <i class="pi pi-chart-bar" />
          <p>No diagnostic data available for this run.</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; }

.empty-state { text-align: center; padding: 48px 0; color: var(--text-color-muted); }
.empty-state i { font-size: 24px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-state p { margin: 0 0 12px; }
.btn-play { color: var(--yellow); margin-right: 6px; }

.results-grid { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }

.model-list { padding: 14px 0; }
.model-list-label { padding: 0 16px 10px; }
.model-row {
  padding: 10px 16px;
  border-left: 3px solid transparent;
  cursor: pointer;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}
.model-row:hover { background: var(--surface-hover); }
.model-row.is-active { border-left-color: var(--yellow); background: var(--surface-ground); }
.model-row-name { font-size: 13.5px; font-weight: 600; }
.model-row-caption { font-size: 11px; color: var(--text-color-muted); margin-top: 2px; }
.model-row-date { font-size: 10.5px; color: var(--surface-500); margin-top: 1px; }

.detail-col { display: flex; flex-direction: column; gap: 16px; }

.properties-card { padding: 18px 20px; }
.properties-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.model-name { font-size: 19px; font-weight: 600; }
.tag-fill {
  background: var(--ink); color: var(--yellow);
  font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 3px 7px; border-radius: 2px;
}
.tag-outline {
  border: 1px solid var(--surface-border-input); color: var(--text-color-secondary);
  font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 3px 7px; border-radius: 2px;
}
.prop-row { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--surface-border-row); font-size: 13px; }
.prop-row:last-child { border-bottom: none; }
.prop-key { flex: none; width: 90px; color: var(--text-color-muted); }
.prop-value { flex: 1; }

.loading-line { padding: 20px; text-align: center; color: var(--text-color-muted); font-size: 13px; }

.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.metric-card { padding: 14px 16px; }
.metric-value { font-size: 24px; font-weight: 600; }
.metric-label { margin-top: 6px; }

.chart-card { padding: 18px 20px; }
.chart-title { font-size: 13.5px; font-weight: 700; margin-bottom: 14px; }

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
.empty-note p { margin: 0 0 12px; font-size: 13px; }

@media (max-width: 900px) {
  .results-grid { grid-template-columns: 1fr; }
  .metric-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
