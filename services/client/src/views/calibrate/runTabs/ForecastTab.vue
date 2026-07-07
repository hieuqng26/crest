<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import calibrationsAPI from '@/api/calibrationsAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'

const props = defineProps({
  run:        { type: Object, required: true },
  segmentKey: { type: String, default: null },
})

const loading   = ref(true)
const error     = ref(null)
const actual    = ref([])
const predicted = ref([])
const meta      = ref({})

onMounted(async () => {
  if (!props.run?.run_id) { loading.value = false; return }
  try {
    const { data } = await calibrationsAPI.forecast(props.run.run_id)
    if (data.length > 0) {
      const parsed = data[0].forecast_json
      actual.value    = parsed.actual    ?? []
      predicted.value = parsed.predicted ?? []
      meta.value      = parsed.meta      ?? {}
    }
  } catch (e) {
    error.value = e?.response?.data?.error ?? e.message
  } finally {
    loading.value = false
  }
})

const isClassification = computed(() => props.run?.model_family === 'classification')

// ── Segment filter ────────────────────────────────────────────────────────────
const segSector     = computed(() => props.segmentKey?.split('__')[0] ?? null)
const segSplitValue = computed(() => props.segmentKey?.split('__').slice(1).join('__') ?? null)
const splitByCol    = computed(() => props.run.seg_split_by ?? null)

const segBaseIndices = computed(() => {
  if (!props.segmentKey || !('sector' in (meta.value ?? {}))) return null
  return actual.value.map((_, i) => i).filter(i => {
    if (meta.value['sector']?.[i] !== segSector.value) return false
    if (!segSplitValue.value) return true
    const col = splitByCol.value ?? 'country'
    return meta.value[col]?.[i] === segSplitValue.value
  })
})
const hasDate          = computed(() => 'date'      in meta.value)
const hasClientId      = computed(() => 'client_id' in meta.value)
const hasCountry       = computed(() => 'country'   in meta.value)

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmtNum = (v) =>
  Math.abs(v) >= 1e9 ? (v / 1e9).toFixed(2) + 'B'
  : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(2) + 'M'
  : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(1) + 'k'
  : v.toFixed(4)

const fmtDate = (d) => {
  if (!d) return d
  const dt = new Date(d)
  const q  = Math.floor(dt.getUTCMonth() / 3) + 1
  return `${dt.getUTCFullYear()} Q${q}`
}

// ── Regression filters ────────────────────────────────────────────────────────
const countryFilter  = ref(null)
const clientIdFilter = ref(null)
const showResidual   = ref(false)
const scatterMode    = ref(false)

const countryOptions = computed(() =>
  [...new Set(meta.value['country'] ?? [])].filter(Boolean).sort()
)

// Available client IDs narrow when a country is selected
const clientIdOptions = computed(() => {
  const clients = meta.value['client_id'] ?? []
  const countries = meta.value['country'] ?? []
  const filtered = countryFilter.value
    ? clients.filter((_, i) => countries[i] === countryFilter.value)
    : clients
  return [...new Set(filtered)].filter(Boolean).sort()
})

// Reset client filter when country changes
watch(countryFilter, () => { clientIdFilter.value = null })

// ── Raw pairs after filters (sorted by date or by actual) ─────────────────────
const regressionPairs = computed(() => {
  const baseSet = segBaseIndices.value
  let pairs = actual.value
    .map((a, i) => ({
      a,
      p:          predicted.value[i],
      origIdx:    i + 1,
      date:       meta.value['date']?.[i]      ?? null,
      client_id:  meta.value['client_id']?.[i] ?? null,
      country:    meta.value['country']?.[i]   ?? null,
      _i:         i,
    }))
    .filter(({ a, p, _i }) => a != null && p != null && (!baseSet || baseSet.includes(_i)))

  if (countryFilter.value)  pairs = pairs.filter(d => d.country   === countryFilter.value)
  if (clientIdFilter.value) pairs = pairs.filter(d => d.client_id === clientIdFilter.value)

  return hasDate.value
    ? [...pairs].sort((x, y) => (x.date ?? '').localeCompare(y.date ?? ''))
    : [...pairs].sort((x, y) => x.a - y.a)
})

// ── Chart data ────────────────────────────────────────────────────────────────
const regressionChartData = computed(() => {
  const pairs = regressionPairs.value
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
      borderColor: '#60a5fa',
      backgroundColor: 'rgba(96,165,250,0.5)',
      pointRadius: pr, showLine: line, tension: 0.1, fill: false, order: 2,
    },
    {
      label: 'Predicted',
      data: pairs.map(d => d.p),
      borderColor: '#34d399',
      backgroundColor: 'rgba(52,211,153,0.5)',
      borderDash: line ? [4, 3] : [],
      pointRadius: pr, showLine: line, tension: 0.1, fill: false, order: 1,
    },
  ]
  if (showResidual.value) {
    datasets.push({
      label: 'Residual',
      data: pairs.map(d => d.a - d.p),
      borderColor: '#f59e0b',
      borderDash: [2, 2],
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
      mode: 'index',
      intersect: false,
      callbacks: {
        label: (ctx) =>
          ` ${ctx.dataset.label}: ${ctx.parsed.y?.toLocaleString(undefined, { maximumFractionDigits: 4 }) ?? '—'}`,
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
        color: '#6b7280',
        font: { size: 11 },
      },
    },
    y: {
      ticks: { color: '#9ca3af' },
      grid:  { color: 'rgba(156,163,175,0.1)' },
    },
  },
}))

// ── Summary stats (full unfiltered) ──────────────────────────────────────────
const regressionStats = computed(() => {
  const pairs = actual.value
    .map((a, i) => ({ a, p: predicted.value[i] }))
    .filter(({ a, p }) => a != null && p != null)
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

// ── Classification ────────────────────────────────────────────────────────────
const BINS       = 10
const BIN_LABELS = Array.from({ length: BINS }, (_, i) =>
  `${(i / BINS).toFixed(1)}–${((i + 1) / BINS).toFixed(1)}`)

const classDistChartData = computed(() => {
  const c0 = new Array(BINS).fill(0)
  const c1 = new Array(BINS).fill(0)
  actual.value.forEach((a, i) => {
    const p = predicted.value[i]
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

// Classification filters
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

const clsFilteredIndices = computed(() => {
  const baseSet = segBaseIndices.value
  const indices = []
  actual.value.forEach((_, i) => {
    if (baseSet && !baseSet.includes(i)) return
    const c = meta.value['client_id']?.[i]
    const co = meta.value['country']?.[i]
    if (clsCountryFilter.value  && co !== clsCountryFilter.value)  return
    if (clsClientIdFilter.value && c  !== clsClientIdFilter.value) return
    indices.push(i)
  })
  return indices
})

// Scatter: prob vs date (or index), coloured by actual class
const classScatterData = computed(() => {
  const pts0 = [], pts1 = []
  clsFilteredIndices.value.forEach((i) => {
    const a = actual.value[i]
    const p = predicted.value[i]
    if (p == null) return
    const xLabel = hasDate.value ? fmtDate(meta.value['date']?.[i]) : i + 1
    const pt = { x: xLabel, y: p }
    ;(Math.round(a) === 0 ? pts0 : pts1).push(pt)
  })
  return {
    datasets: [
      { label: 'Actual = 0', data: pts0, backgroundColor: 'rgba(96,165,250,0.6)',  pointRadius: 2 },
      { label: 'Actual = 1', data: pts1, backgroundColor: 'rgba(248,113,113,0.6)', pointRadius: 2 },
    ],
  }
})

const classScatterOptions = computed(() => ({
  maintainAspectRatio: false, animation: false,
  plugins: {
    legend: { labels: { color: '#9ca3af', usePointStyle: true, pointStyleWidth: 10 } },
    tooltip: { callbacks: {
      label: (ctx) => ` P(positive)=${ctx.parsed.y?.toFixed(4)}`,
    }},
  },
  scales: {
    x: { type: 'category', ticks: { color: '#9ca3af', maxTicksLimit: 12 }, grid: { color: 'rgba(156,163,175,0.1)' },
         title: { display: true, text: hasDate.value ? 'Date' : 'Observation index', color: '#6b7280', font: { size: 11 } } },
    y: { min: 0, max: 1, ticks: { color: '#9ca3af' }, grid: { color: 'rgba(156,163,175,0.1)' },
         title: { display: true, text: 'Predicted probability', color: '#6b7280', font: { size: 11 } } },
  },
}))

const classStats = computed(() => {
  if (!isClassification.value) return null
  const n = actual.value.length
  const pos = actual.value.filter(v => Math.round(v) === 1).length
  let tp = 0, tn = 0, fp = 0, fn = 0
  actual.value.forEach((a, i) => {
    const pred = predicted.value[i] >= 0.5 ? 1 : 0
    const act  = Math.round(a)
    if (act === 1 && pred === 1) tp++
    else if (act === 0 && pred === 0) tn++
    else if (act === 0 && pred === 1) fp++
    else fn++
  })
  const precision = tp + fp > 0 ? tp / (tp + fp) : 0
  const recall    = tp + fn > 0 ? tp / (tp + fn) : 0
  const f1        = precision + recall > 0 ? 2 * precision * recall / (precision + recall) : 0
  return [
    { label: 'Total',     value: n.toLocaleString() },
    { label: 'Positives', value: `${pos} (${(pos / n * 100).toFixed(1)}%)` },
    { label: 'Precision', value: precision.toFixed(4) },
    { label: 'Recall',    value: recall.toFixed(4) },
    { label: 'F1',        value: f1.toFixed(4) },
  ]
})

// ── Prediction table (server-paginated) ────────────────────────────────────────
// Independent of the chart's country/client filters above — the table has its
// own per-column filters (including these) via CommonDataTable.
const predictionColumns = computed(() => {
  const cols = []
  if (hasDate.value)     cols.push({ field: 'date',      header: 'Date',    width: '9rem' })
  if (hasClientId.value) cols.push({ field: 'client_id', header: 'Client',  width: '8rem' })
  if (hasCountry.value)  cols.push({ field: 'country',   header: 'Country', width: '8rem' })
  if (isClassification.value) {
    cols.push({ field: 'actual',     header: 'Actual class' })
    cols.push({ field: 'predicted',  header: 'P(positive)', formatter: (v) => v?.toFixed(4) ?? '—' })
    cols.push({ field: 'pred_class', header: 'Predicted class' })
    cols.push({ field: 'correct',    header: '', width: '3rem', sortable: false, filterable: false })
  } else {
    cols.push({ field: 'actual',    header: 'Actual',    formatter: (v) => v?.toFixed(4) ?? '—' })
    cols.push({ field: 'predicted', header: 'Predicted', formatter: (v) => v?.toFixed(4) ?? '—' })
    cols.push({ field: 'residual',  header: 'Residual',  formatter: (v) => v?.toFixed(4) ?? '—' })
  }
  return cols
})

const predictionsFetchPage = (params) => calibrationsAPI.backtestPredictions(props.run.run_id, params)
const predictionsFetchDistinct = (field) => calibrationsAPI.backtestPredictionsDistinct(props.run.run_id, field)
</script>

<template>
  <div class="flex flex-column gap-4">

    <div v-if="loading" class="text-center py-8 text-color-secondary">
      <i class="pi pi-spin pi-spinner text-2xl block mb-2" />
      Loading predictions…
    </div>

    <div v-else-if="error" class="empty-state">
      <i class="pi pi-exclamation-triangle text-3xl block mb-2 opacity-50" />
      <p class="m-0 text-color-secondary">{{ error }}</p>
    </div>

    <div v-else-if="actual.length === 0" class="empty-state">
      <i class="pi pi-chart-line text-3xl block mb-2 opacity-50" />
      <p class="m-0 text-color-secondary">No forecast data available for this run.</p>
    </div>

    <template v-else>

      <!-- Segment filter notice -->
      <div v-if="segmentKey" class="flex align-items-center gap-2 mb-3 surface-ground border-round px-3 py-2">
        <i class="pi pi-filter text-xs text-color-secondary" />
        <span class="text-xs text-color-secondary">
          Segment: <strong class="font-mono">{{ segmentKey }}</strong>
          <template v-if="!('sector' in (meta ?? {}))"> — no sector column in data, showing all rows</template>
        </span>
      </div>

      <!-- ── Classification ────────────────────────────────────────────── -->
      <template v-if="isClassification">
        <!-- Stats strip -->
        <div class="surface-card border-round overflow-hidden" style="border:1px solid var(--surface-border)">
          <div class="flex">
            <div v-for="s in classStats" :key="s.label"
              class="flex flex-column px-4 py-3 text-center flex-1"
              style="border-right:1px solid var(--surface-border)">
              <span class="font-bold text-blue-400">{{ s.value }}</span>
              <span class="text-xs text-color-secondary mt-1">{{ s.label }}</span>
            </div>
          </div>
        </div>

        <!-- Distribution histogram -->
        <div class="surface-card border-round p-4" style="border:1px solid var(--surface-border)">
          <div class="flex align-items-center justify-content-between mb-3">
            <h4 class="text-sm font-semibold m-0">Predicted Probability Distribution by Actual Class</h4>
            <span class="text-xs text-color-secondary">A good model separates the two distributions</span>
          </div>
          <div style="height:240px">
            <Chart type="bar" :data="classDistChartData" :options="classDistOptions" class="h-full" />
          </div>
        </div>

        <!-- Scatter + filters -->
        <div class="surface-card border-round p-4" style="border:1px solid var(--surface-border)">
          <div class="flex align-items-center justify-content-between mb-3">
            <h4 class="text-sm font-semibold m-0">Predicted Probability — per Observation</h4>
            <span class="text-xs text-color-secondary">{{ clsFilteredIndices.length.toLocaleString() }} observations</span>
          </div>

          <!-- Filters -->
          <div v-if="hasCountry || hasClientId" class="flex align-items-center gap-3 flex-wrap mb-3">
            <div v-if="hasCountry" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Country</span>
              <EySelect v-model="clsCountryFilter" :options="clsCountryOptions"
                        placeholder="All" showClear class="ctrl-drop" />
            </div>
            <div v-if="hasClientId" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Client</span>
              <EySelect v-model="clsClientIdFilter" :options="clsClientIdOptions"
                        placeholder="All" showClear filter class="ctrl-drop" style="min-width:9rem" />
            </div>
          </div>

          <div style="height:220px">
            <Chart type="scatter" :data="classScatterData" :options="classScatterOptions" class="h-full" />
          </div>
        </div>

        <!-- Table -->
        <div class="surface-card border-round p-4" style="border:1px solid var(--surface-border)">
          <h4 class="text-sm font-semibold m-0 mb-3">Predictions</h4>
          <CommonDataTable
            :key="run.run_id"
            :columns="predictionColumns"
            :fetch-page="predictionsFetchPage"
            :fetch-distinct="predictionsFetchDistinct"
            empty-message="No predictions available."
          >
            <template #cell-correct="{ data }">
              <span :style="{ color: data.correct ? '#34d399' : '#f87171' }">{{ data.correct ? '✓' : '✗' }}</span>
            </template>
          </CommonDataTable>
        </div>
      </template>

      <!-- ── Regression ─────────────────────────────────────────────────── -->
      <template v-else>
        <!-- Stats strip -->
        <div class="surface-card border-round overflow-hidden" style="border:1px solid var(--surface-border)">
          <div class="flex">
            <div v-for="s in regressionStats" :key="s.label"
              class="flex flex-column px-4 py-3 text-center flex-1"
              style="border-right:1px solid var(--surface-border)">
              <span class="font-mono text-sm font-semibold">{{ s.value }}</span>
              <span class="text-xs text-color-secondary mt-1">{{ s.label }}</span>
            </div>
          </div>
        </div>

        <!-- Chart card -->
        <div class="surface-card border-round p-4" style="border:1px solid var(--surface-border)">
          <div class="flex align-items-center justify-content-between mb-3">
            <h4 class="text-sm font-semibold m-0">Actual vs Predicted — Validation Set</h4>
            <span class="text-xs text-color-secondary">
              {{ regressionPairs.length.toLocaleString() }} observations
            </span>
          </div>

          <!-- Controls: filters left, toggles right -->
          <div class="flex align-items-center gap-3 flex-wrap mb-3">
            <div v-if="hasCountry" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Country</span>
              <EySelect v-model="countryFilter" :options="countryOptions"
                        placeholder="All" showClear class="ctrl-drop" />
            </div>
            <div v-if="hasClientId" class="flex align-items-center gap-2">
              <span class="text-xs text-color-secondary">Client</span>
              <EySelect v-model="clientIdFilter" :options="clientIdOptions"
                        placeholder="All" showClear filter class="ctrl-drop" style="min-width:9rem" />
            </div>
            <div class="flex gap-2 ml-auto">
              <Button
                :label="showResidual ? 'Residual on' : 'Residual'"
                :outlined="!showResidual"
                :severity="showResidual ? undefined : 'secondary'"
                size="small" icon="pi pi-minus" class="ctrl-btn"
                @click="showResidual = !showResidual"
              />
              <Button
                :label="scatterMode ? 'Scatter' : 'Line'"
                :outlined="!scatterMode"
                :severity="scatterMode ? undefined : 'secondary'"
                size="small" :icon="scatterMode ? 'pi pi-circle' : 'pi pi-chart-line'"
                class="ctrl-btn"
                @click="scatterMode = !scatterMode"
              />
            </div>
          </div>

          <div style="height:360px">
            <Chart type="line" :data="regressionChartData" :options="regressionOptions" class="h-full" />
          </div>
        </div>

        <!-- Predictions table -->
        <div class="surface-card border-round p-4" style="border:1px solid var(--surface-border)">
          <h4 class="text-sm font-semibold m-0 mb-3">Prediction values</h4>
          <CommonDataTable
            :key="run.run_id"
            :columns="predictionColumns"
            :fetch-page="predictionsFetchPage"
            :fetch-distinct="predictionsFetchDistinct"
            empty-message="No predictions available."
          >
            <template #cell-residual="{ data }">
              <span :style="{ color: data.residual < 0 ? '#f87171' : '#34d399' }">
                {{ data.residual?.toFixed(4) ?? '—' }}
              </span>
            </template>
          </CommonDataTable>
        </div>
      </template>

    </template>
  </div>
</template>

<style scoped>
.empty-state { text-align: center; padding: 3rem 1rem; }

.ctrl-drop { height: 2rem; min-width: 9rem; }
:deep(.ctrl-drop .p-dropdown-label) { padding: 0.3rem 0.5rem; font-size: 0.78rem; white-space: nowrap; overflow: visible; }
:deep(.ctrl-drop .p-dropdown-trigger) { width: 2rem; }
.ctrl-btn { font-size: 0.78rem; height: 2rem; padding: 0 0.65rem; }
</style>
