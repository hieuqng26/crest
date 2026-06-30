<script setup>
import { ref, computed, watch } from 'vue'
import calibrationsAPI from '@/api/calibrationsAPI'

const props = defineProps({
  run:        { type: Object, required: true },
  segmentKey: { type: String, default: null },
})

const diag    = ref(null)
const loading = ref(false)

watch(
  () => props.segmentKey,
  async (key) => {
    if (!key) { diag.value = null; return }
    loading.value = true
    try {
      const { data } = await calibrationsAPI.getDiagnostics(props.run.run_id, key)
      diag.value = data.metrics ?? null
    } catch {
      diag.value = null
    } finally {
      loading.value = false
    }
  },
  { immediate: true }
)

// ── Data source detection ─────────────────────────────────────────────────────
// val_obs is present on runs calibrated after the backend was updated to store
// per-observation data. Older runs fall back to fitted/residuals for regression
// and to aggregate metrics (confusion matrix, ROC) for classification.
const obs     = computed(() => diag.value?.val_obs ?? null)
const hasValObs = computed(() => obs.value !== null && (obs.value.actual?.length ?? 0) > 0)

const isClassification = computed(() => props.run?.model_family === 'classification')

// Regression fallback data from fitted/residuals
const fallbackFitted    = computed(() => diag.value?.fitted    ?? [])
const fallbackResiduals = computed(() => diag.value?.residuals ?? [])
const hasFallbackReg    = computed(() => fallbackFitted.value.length > 0)

// Classification fallback: diag has confusion_matrix
const hasFallbackCls = computed(() => !!(diag.value?.confusion_matrix))

const hasAnyData = computed(() =>
  hasValObs.value ||
  (isClassification.value ? hasFallbackCls.value : hasFallbackReg.value)
)

// ── Meta arrays (only from val_obs) ──────────────────────────────────────────
const meta      = computed(() => obs.value?.meta ?? {})
const hasDate     = computed(() => hasValObs.value && 'date'      in meta.value)
const hasClientId = computed(() => hasValObs.value && 'client_id' in meta.value)
const hasCountry  = computed(() => hasValObs.value && 'country'   in meta.value)

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmtNum = (v) =>
  Math.abs(v) >= 1e9 ? (v / 1e9).toFixed(2) + 'B'
  : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(2) + 'M'
  : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(1) + 'k'
  : v.toFixed(4)

const fmtDate = (d) => {
  if (!d) return String(d)
  const dt = new Date(d)
  const q  = Math.floor(dt.getUTCMonth() / 3) + 1
  return `${dt.getUTCFullYear()} Q${q}`
}

// ── Regression ────────────────────────────────────────────────────────────────
const countryFilter  = ref(null)
const clientIdFilter = ref(null)
const showResidual   = ref(false)
const scatterMode    = ref(false)

const countryOptions = computed(() =>
  [...new Set(meta.value['country'] ?? [])].filter(Boolean).sort()
)
const clientIdOptions = computed(() => {
  const clients   = meta.value['client_id'] ?? []
  const countries = meta.value['country']   ?? []
  const filtered  = countryFilter.value
    ? clients.filter((_, i) => countries[i] === countryFilter.value)
    : clients
  return [...new Set(filtered)].filter(Boolean).sort()
})
watch(countryFilter, () => { clientIdFilter.value = null })

const regressionPairs = computed(() => {
  let rawActual, rawPredicted, rawDate, rawClientId, rawCountry

  if (hasValObs.value) {
    rawActual    = obs.value.actual
    rawPredicted = obs.value.predicted
    rawDate      = meta.value['date']      ?? []
    rawClientId  = meta.value['client_id'] ?? []
    rawCountry   = meta.value['country']   ?? []
  } else {
    // Fallback: reconstruct actuals from fitted + residuals
    const fitted    = fallbackFitted.value
    const residuals = fallbackResiduals.value
    rawActual    = fitted.map((f, i) => f + (residuals[i] ?? 0))
    rawPredicted = fitted
    rawDate      = []
    rawClientId  = []
    rawCountry   = []
  }

  let pairs = rawActual
    .map((a, i) => ({
      a,
      p:         rawPredicted[i],
      date:      rawDate[i]     ?? null,
      client_id: rawClientId[i] ?? null,
      country:   rawCountry[i]  ?? null,
    }))
    .filter(({ a, p }) => a != null && p != null)

  if (countryFilter.value)  pairs = pairs.filter(d => d.country   === countryFilter.value)
  if (clientIdFilter.value) pairs = pairs.filter(d => d.client_id === clientIdFilter.value)

  return hasDate.value
    ? [...pairs].sort((x, y) => (x.date ?? '').localeCompare(y.date ?? ''))
    : [...pairs].sort((x, y) => x.a - y.a)
})

const regressionStats = computed(() => {
  const pairs = regressionPairs.value
  if (!pairs.length) return []
  const n     = pairs.length
  const meanA = pairs.reduce((s, d) => s + d.a, 0) / n
  const resids = pairs.map(d => d.a - d.p)
  const abs    = resids.map(Math.abs)
  const mae    = abs.reduce((s, r) => s + r, 0) / n
  const rmse   = Math.sqrt(resids.reduce((s, r) => s + r * r, 0) / n)
  const ssTot  = pairs.reduce((s, d) => s + (d.a - meanA) ** 2, 0)
  const r2     = ssTot > 0 ? 1 - resids.reduce((s, r) => s + r * r, 0) / ssTot : 0
  const sorted = [...abs].sort((a, b) => a - b)
  return [
    { label: 'N',            value: n.toLocaleString() },
    { label: 'MAE',          value: fmtNum(mae) },
    { label: 'RMSE',         value: fmtNum(rmse) },
    { label: 'R²',           value: r2.toFixed(4) },
    { label: 'Median |err|', value: fmtNum(sorted[Math.floor(n / 2)]) },
    { label: 'Max |err|',    value: fmtNum(sorted[n - 1]) },
  ]
})

const regressionChartData = computed(() => {
  const pairs = regressionPairs.value
  if (!pairs.length) return null
  const large = pairs.length > 500
  const pr    = scatterMode.value ? (large ? 1 : 2) : 0
  const line  = !scatterMode.value
  const labels = hasDate.value
    ? pairs.map(d => fmtDate(d.date))
    : pairs.map((_, i) => i + 1)
  const datasets = [
    {
      label: 'Actual',
      data: pairs.map(d => d.a),
      borderColor: '#60a5fa', backgroundColor: 'rgba(96,165,250,0.5)',
      pointRadius: pr, showLine: line, tension: 0.1, fill: false, order: 2,
    },
    {
      label: 'Predicted',
      data: pairs.map(d => d.p),
      borderColor: '#34d399', borderDash: line ? [4, 3] : [],
      backgroundColor: 'rgba(52,211,153,0.5)',
      pointRadius: pr, showLine: line, tension: 0.1, fill: false, order: 1,
    },
  ]
  if (showResidual.value) {
    datasets.push({
      label: 'Residual',
      data: pairs.map(d => d.a - d.p),
      borderColor: '#f59e0b', borderDash: [2, 2],
      pointRadius: pr, showLine: line, tension: 0, fill: false, order: 0,
    })
  }
  return { labels, datasets }
})

const regressionOptions = computed(() => ({
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { labels: { color: '#9ca3af', usePointStyle: true, pointStyleWidth: 10 } },
    tooltip: {
      mode: 'index', intersect: false,
      callbacks: {
        label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y?.toLocaleString(undefined, { maximumFractionDigits: 4 }) ?? '—'}`,
      },
    },
  },
  scales: {
    x: {
      ticks: { color: '#9ca3af', maxTicksLimit: 12 },
      grid:  { color: 'rgba(156,163,175,0.1)' },
      title: {
        display: true,
        text: hasDate.value ? 'Date' : 'Observations (sorted by actual)',
        color: '#6b7280', font: { size: 11 },
      },
    },
    y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' } },
  },
}))

const regressionTableRows = computed(() =>
  regressionPairs.value.map((d, i) => ({
    idx:       i + 1,
    date:      d.date      ?? '—',
    client_id: d.client_id ?? '—',
    country:   d.country   ?? '—',
    actual:    d.a?.toFixed(4) ?? '—',
    predicted: d.p?.toFixed(4) ?? '—',
    residual:  (d.a != null && d.p != null) ? (d.a - d.p).toFixed(4) : '—',
  }))
)
const regressionFirst = ref(0)

// ── Classification — val_obs mode ─────────────────────────────────────────────
const clsCountryFilter  = ref(null)
const clsClientIdFilter = ref(null)

const clsCountryOptions = computed(() =>
  [...new Set(meta.value['country'] ?? [])].filter(Boolean).sort()
)
const clsClientIdOptions = computed(() => {
  const clients   = meta.value['client_id'] ?? []
  const countries = meta.value['country']   ?? []
  const filtered  = clsCountryFilter.value
    ? clients.filter((_, i) => countries[i] === clsCountryFilter.value)
    : clients
  return [...new Set(filtered)].filter(Boolean).sort()
})
watch(clsCountryFilter, () => { clsClientIdFilter.value = null })

const clsActual    = computed(() => obs.value?.actual    ?? [])
const clsPredicted = computed(() => obs.value?.predicted ?? [])

const BINS       = 10
const BIN_LABELS = Array.from({ length: BINS }, (_, i) =>
  `${(i / BINS).toFixed(1)}–${((i + 1) / BINS).toFixed(1)}`)

const classDistChartData = computed(() => {
  const c0 = new Array(BINS).fill(0)
  const c1 = new Array(BINS).fill(0)
  clsActual.value.forEach((a, i) => {
    const p = clsPredicted.value[i]
    if (p == null) return
    const bin = Math.min(Math.floor(p * BINS), BINS - 1)
    ;(Math.round(a) === 0 ? c0 : c1)[bin]++
  })
  return {
    labels: BIN_LABELS,
    datasets: [
      { label: 'Actual = 0', data: c0, backgroundColor: 'rgba(96,165,250,0.7)',  borderColor: '#60a5fa', borderWidth: 1, borderRadius: 3 },
      { label: 'Actual = 1', data: c1, backgroundColor: 'rgba(248,113,113,0.7)', borderColor: '#f87171', borderWidth: 1, borderRadius: 3 },
    ],
  }
})

const classDistOptions = {
  maintainAspectRatio: false, animation: false,
  plugins: {
    legend: { labels: { color: '#9ca3af', usePointStyle: true, pointStyleWidth: 10 } },
    tooltip: { callbacks: {
      title: (items) => `Predicted probability: ${items[0].label}`,
      label: (ctx)  => ` ${ctx.dataset.label}: ${ctx.parsed.y} observations`,
    }},
  },
  scales: {
    x: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' },
         title: { display: true, text: 'Predicted probability', color: '#6b7280', font: { size: 11 } } },
    y: { ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' },
         title: { display: true, text: 'Count', color: '#6b7280', font: { size: 11 } } },
  },
}

// ── Classification — fallback (aggregate diag) ────────────────────────────────
const clsKpis = computed(() => {
  if (!diag.value) return []
  const fields = [
    ['AUC-ROC', 'auc_roc'], ['Accuracy', 'accuracy'], ['Precision', 'precision'],
    ['Recall', 'recall'], ['F1', 'f1'], ['KS', 'ks'], ['Gini', 'gini'],
  ]
  return fields
    .filter(([, k]) => diag.value[k] != null)
    .map(([label, k]) => ({ label, value: Number(diag.value[k]).toFixed(4) }))
})

const cmMatrix = computed(() => {
  const cm = diag.value?.confusion_matrix
  if (!cm) return null
  let tn, fp, fn, tp
  if (Array.isArray(cm[0])) {
    [[tn, fp], [fn, tp]] = cm
  } else {
    [tn, fp, fn, tp] = cm
  }
  const total = (tn + fp + fn + tp) || 1
  return { tn, fp, fn, tp, total }
})

const rocChartData = computed(() => {
  const roc = diag.value?.roc_curve
  if (!roc?.fpr?.length) return null
  return {
    datasets: [{
      label: 'ROC curve',
      data: roc.fpr.map((x, i) => ({ x, y: roc.tpr[i] })),
      borderColor: '#818cf8', backgroundColor: 'transparent',
      pointRadius: 0, showLine: true, tension: 0,
    }, {
      label: 'Random',
      data: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
      borderColor: 'rgba(156,163,175,0.3)', borderDash: [4, 4],
      pointRadius: 0, showLine: true,
    }],
  }
})

const rocOptions = {
  maintainAspectRatio: false, animation: false,
  plugins: {
    legend: { labels: { color: '#9ca3af', usePointStyle: true, pointStyleWidth: 10 } },
    tooltip: { callbacks: { label: (ctx) => ` TPR=${ctx.parsed.y?.toFixed(3)} @ FPR=${ctx.parsed.x?.toFixed(3)}` } },
  },
  scales: {
    x: { type: 'linear', min: 0, max: 1,
         ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' },
         title: { display: true, text: 'False Positive Rate', color: '#6b7280', font: { size: 11 } } },
    y: { min: 0, max: 1,
         ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' },
         title: { display: true, text: 'True Positive Rate', color: '#6b7280', font: { size: 11 } } },
  },
}

// ── Shared download ───────────────────────────────────────────────────────────
function downloadCsv(rows, filename) {
  if (!rows.length) return
  const headers = Object.keys(rows[0])
  const lines = [headers.join(','), ...rows.map(r => headers.map(h => JSON.stringify(r[h] ?? '')).join(','))]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <div>
    <div v-if="loading" class="text-center py-8 text-color-secondary">
      <i class="pi pi-spin pi-spinner text-2xl block mb-2" />
      Loading backtesting data…
    </div>

    <div v-else-if="!hasAnyData" class="empty-state">
      <i class="pi pi-chart-line text-3xl block mb-2 opacity-40" />
      <p class="m-0">No backtesting data available for this segment.</p>
    </div>

    <div v-else class="flex flex-column gap-4">

      <!-- ── Classification ─────────────────────────────────────────────── -->
      <template v-if="isClassification">

        <!-- KPI strip (always from diag scalars) -->
        <div v-if="clsKpis.length" class="surface-card border-round overflow-hidden" style="border: 1px solid var(--surface-border)">
          <div class="flex">
            <div v-for="s in clsKpis" :key="s.label"
              class="flex flex-column px-4 py-3 text-center flex-1"
              style="border-right: 1px solid var(--surface-border)">
              <span class="font-mono text-sm font-semibold">{{ s.value }}</span>
              <span class="text-xs text-color-secondary mt-1">{{ s.label }}</span>
            </div>
          </div>
        </div>

        <!-- val_obs path: distribution histogram + per-obs scatter -->
        <template v-if="hasValObs">
          <div class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
            <div class="flex align-items-center justify-content-between mb-3">
              <h4 class="text-sm font-semibold m-0">Predicted Probability Distribution by Actual Class</h4>
              <span class="text-xs text-color-secondary">A good model separates the two distributions</span>
            </div>
            <div style="height: 240px">
              <Chart type="bar" :data="classDistChartData" :options="classDistOptions" class="h-full" />
            </div>
          </div>

          <!-- Filters -->
          <div v-if="hasCountry || hasClientId" class="flex align-items-center gap-3 flex-wrap">
            <div v-if="hasCountry" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Country</span>
              <Dropdown v-model="clsCountryFilter" :options="clsCountryOptions" placeholder="All" showClear class="ctrl-drop" />
            </div>
            <div v-if="hasClientId" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Client</span>
              <Dropdown v-model="clsClientIdFilter" :options="clsClientIdOptions" placeholder="All" showClear filter class="ctrl-drop" style="min-width: 9rem" />
            </div>
          </div>
        </template>

        <!-- Fallback path: confusion matrix + ROC -->
        <template v-else>
          <div v-if="cmMatrix" class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
            <h4 class="text-sm font-semibold m-0 mb-3">Confusion Matrix (validation set)</h4>
            <div class="confusion-grid">
              <div class="cf-cell cf-header">Predicted 0</div>
              <div class="cf-cell cf-header">Predicted 1</div>
              <div class="cf-cell cf-actual-label">Actual 0</div>
              <div class="cf-cell cf-tn">
                <div class="cf-count">{{ cmMatrix.tn.toLocaleString() }}</div>
                <div class="cf-pct">{{ (cmMatrix.tn / cmMatrix.total * 100).toFixed(1) }}%</div>
                <div class="cf-label">TN</div>
              </div>
              <div class="cf-cell cf-fp">
                <div class="cf-count">{{ cmMatrix.fp.toLocaleString() }}</div>
                <div class="cf-pct">{{ (cmMatrix.fp / cmMatrix.total * 100).toFixed(1) }}%</div>
                <div class="cf-label">FP</div>
              </div>
              <div class="cf-cell cf-actual-label">Actual 1</div>
              <div class="cf-cell cf-fn">
                <div class="cf-count">{{ cmMatrix.fn.toLocaleString() }}</div>
                <div class="cf-pct">{{ (cmMatrix.fn / cmMatrix.total * 100).toFixed(1) }}%</div>
                <div class="cf-label">FN</div>
              </div>
              <div class="cf-cell cf-tp">
                <div class="cf-count">{{ cmMatrix.tp.toLocaleString() }}</div>
                <div class="cf-pct">{{ (cmMatrix.tp / cmMatrix.total * 100).toFixed(1) }}%</div>
                <div class="cf-label">TP</div>
              </div>
            </div>
          </div>

          <div v-if="rocChartData" class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
            <h4 class="text-sm font-semibold m-0 mb-3">ROC Curve (validation set)</h4>
            <div style="height: 260px">
              <Chart type="scatter" :data="rocChartData" :options="rocOptions" class="h-full" />
            </div>
          </div>
        </template>

      </template>

      <!-- ── Regression ─────────────────────────────────────────────────── -->
      <template v-else>

        <!-- Stats strip -->
        <div v-if="regressionStats.length" class="surface-card border-round overflow-hidden" style="border: 1px solid var(--surface-border)">
          <div class="flex">
            <div v-for="s in regressionStats" :key="s.label"
              class="flex flex-column px-4 py-3 text-center flex-1"
              style="border-right: 1px solid var(--surface-border)">
              <span class="font-mono text-sm font-semibold">{{ s.value }}</span>
              <span class="text-xs text-color-secondary mt-1">{{ s.label }}</span>
            </div>
          </div>
        </div>

        <!-- Chart -->
        <div class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
          <div class="flex align-items-center justify-content-between mb-3">
            <h4 class="text-sm font-semibold m-0">Actual vs Predicted — Validation Set</h4>
            <span class="text-xs text-color-secondary">{{ regressionPairs.length.toLocaleString() }} observations</span>
          </div>

          <!-- Filters (only if val_obs present) -->
          <div v-if="hasValObs && (hasCountry || hasClientId)" class="flex align-items-center gap-3 flex-wrap mb-3">
            <div v-if="hasCountry" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Country</span>
              <Dropdown v-model="countryFilter" :options="countryOptions" placeholder="All" showClear class="ctrl-drop" />
            </div>
            <div v-if="hasClientId" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Client</span>
              <Dropdown v-model="clientIdFilter" :options="clientIdOptions" placeholder="All" showClear filter class="ctrl-drop" style="min-width: 9rem" />
            </div>
          </div>

          <div class="flex gap-2 justify-content-end mb-3">
            <Button
              :label="showResidual ? 'Residual on' : 'Residual'"
              :outlined="!showResidual" :severity="showResidual ? undefined : 'secondary'"
              size="small" icon="pi pi-minus" class="ctrl-btn"
              @click="showResidual = !showResidual"
            />
            <Button
              :label="scatterMode ? 'Scatter' : 'Line'"
              :outlined="!scatterMode" :severity="scatterMode ? undefined : 'secondary'"
              size="small" :icon="scatterMode ? 'pi pi-circle' : 'pi pi-chart-line'"
              class="ctrl-btn"
              @click="scatterMode = !scatterMode"
            />
          </div>

          <div style="height: 360px">
            <Chart v-if="regressionChartData" type="line" :data="regressionChartData" :options="regressionOptions" class="h-full" />
          </div>
        </div>

        <!-- Table -->
        <div class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
          <div class="flex align-items-center justify-content-between mb-3">
            <h4 class="text-sm font-semibold m-0">
              Prediction values
              <span class="text-xs font-normal text-color-secondary ml-2">{{ regressionPairs.length.toLocaleString() }} rows</span>
            </h4>
            <Button label="Download CSV" icon="pi pi-download" size="small" severity="secondary" outlined
              @click="downloadCsv(regressionTableRows, `backtesting_${segmentKey}.csv`)" />
          </div>
          <DataTable :value="regressionTableRows" size="small" class="bt-table"
            :paginator="regressionTableRows.length > 25" :rows="25" v-model:first="regressionFirst">
            <template #paginatorstart>
              <span class="text-xs text-color-secondary">
                {{ regressionTableRows.length === 0 ? '0' : regressionFirst + 1 }}–{{ Math.min(regressionFirst + 25, regressionTableRows.length) }} of {{ regressionTableRows.length.toLocaleString() }}
              </span>
            </template>
            <Column field="idx"       header="#"         style="width: 4rem" />
            <Column field="date"      header="Date"      v-if="hasDate"     style="font-family: monospace; white-space: nowrap" />
            <Column field="client_id" header="Client"    v-if="hasClientId" style="font-family: monospace" />
            <Column field="country"   header="Country"   v-if="hasCountry"  />
            <Column field="actual"    header="Actual"    style="font-family: monospace" />
            <Column field="predicted" header="Predicted" style="font-family: monospace" />
            <Column field="residual"  header="Residual"  style="font-family: monospace">
              <template #body="{ data }">
                <span :style="{ color: parseFloat(data.residual) < 0 ? '#f87171' : '#34d399' }">{{ data.residual }}</span>
              </template>
            </Column>
          </DataTable>
        </div>

      </template>

    </div>
  </div>
</template>

<style scoped>
.ctrl-drop { height: 2rem; min-width: 9rem; }
:deep(.ctrl-drop .p-dropdown-label) { padding: 0.3rem 0.5rem; font-size: 0.78rem; white-space: nowrap; overflow: visible; }
:deep(.ctrl-drop .p-dropdown-trigger) { width: 2rem; }
.ctrl-btn { font-size: 0.78rem; height: 2rem; padding: 0 0.65rem; }

:deep(.bt-table .p-datatable-thead > tr > th) {
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}
:deep(.bt-table .p-datatable-tbody > tr > td) {
  padding: 0.35rem 0.75rem;
  font-size: 0.82rem;
  border-bottom: 1px solid var(--surface-border);
}
:deep(.bt-table .p-datatable-tbody > tr:hover > td) {
  background: var(--surface-hover);
}

/* Confusion matrix */
.confusion-grid {
  display: grid;
  grid-template-columns: auto 1fr 1fr;
  gap: 2px;
  max-width: 480px;
}
.cf-cell { padding: 0.6rem 1rem; border-radius: 4px; }
.cf-header { background: var(--surface-ground); color: var(--text-color-secondary); font-size: 0.75rem; font-weight: 600; text-align: center; }
.cf-actual-label { background: transparent; color: var(--text-color-secondary); font-size: 0.75rem; font-weight: 600; display: flex; align-items: center; }
.cf-count { font-size: 1.25rem; font-weight: 700; font-family: monospace; }
.cf-pct   { font-size: 0.72rem; color: var(--text-color-secondary); }
.cf-label { font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 2px; }
.cf-tn { background: rgba(52,  211, 153, 0.15); } .cf-tn .cf-label { color: #34d399; }
.cf-tp { background: rgba(52,  211, 153, 0.15); } .cf-tp .cf-label { color: #34d399; }
.cf-fp { background: rgba(248, 113, 113, 0.12); } .cf-fp .cf-label { color: #f87171; }
.cf-fn { background: rgba(248, 113, 113, 0.12); } .cf-fn .cf-label { color: #f87171; }

.empty-state { text-align: center; padding: 4rem 2rem; border: 1px dashed var(--surface-border); border-radius: 10px; color: var(--text-color-secondary); }
</style>
