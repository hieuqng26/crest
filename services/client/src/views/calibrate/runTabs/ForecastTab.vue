<script setup>
import { ref, computed, onMounted } from 'vue'
import calibrationsAPI from '@/api/calibrationsAPI'

const props = defineProps({ run: { type: Object, required: true } })

const loading = ref(true)
const error   = ref(null)
const actual    = ref([])
const predicted = ref([])

onMounted(async () => {
  if (!props.run?.run_id) { loading.value = false; return }
  try {
    const { data } = await calibrationsAPI.forecast(props.run.run_id)
    if (data.length > 0) {
      const parsed = JSON.parse(data[0].forecast_json)
      actual.value    = parsed.actual    ?? []
      predicted.value = parsed.predicted ?? []
    }
  } catch (e) {
    error.value = e?.response?.data?.error ?? e.message
  } finally {
    loading.value = false
  }
})

// Use model family from run metadata — never guess from data values
const isClassification = computed(() => props.run?.model_family === 'classification')

// ── Classification: predicted probability distribution by actual class ──────
const BINS = 10
const BIN_LABELS = Array.from({ length: BINS }, (_, i) =>
  `${(i / BINS).toFixed(1)}–${((i + 1) / BINS).toFixed(1)}`
)

const classDistChartData = computed(() => {
  const counts0 = new Array(BINS).fill(0)
  const counts1 = new Array(BINS).fill(0)
  actual.value.forEach((a, i) => {
    const p = predicted.value[i]
    if (p == null) return
    const bin = Math.min(Math.floor(p * BINS), BINS - 1)
    if (Math.round(a) === 0) counts0[bin]++
    else counts1[bin]++
  })
  return {
    labels: BIN_LABELS,
    datasets: [
      {
        label: 'Actual = 0',
        data: counts0,
        backgroundColor: 'rgba(96,165,250,0.7)',
        borderColor: '#60a5fa',
        borderWidth: 1,
        borderRadius: 3,
      },
      {
        label: 'Actual = 1',
        data: counts1,
        backgroundColor: 'rgba(248,113,113,0.7)',
        borderColor: '#f87171',
        borderWidth: 1,
        borderRadius: 3,
      },
    ],
  }
})

const classDistOptions = {
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { labels: { color: '#9ca3af', usePointStyle: true, pointStyleWidth: 10 } },
    tooltip: {
      callbacks: {
        title: (items) => `Predicted probability: ${items[0].label}`,
        label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y} observations`,
      },
    },
  },
  scales: {
    x: {
      ticks: { color: '#9ca3af' },
      grid:  { color: 'rgba(156,163,175,0.1)' },
      title: { display: true, text: 'Predicted probability', color: '#6b7280', font: { size: 11 } },
    },
    y: {
      ticks: { color: '#9ca3af' },
      grid:  { color: 'rgba(156,163,175,0.1)' },
      title: { display: true, text: 'Count', color: '#6b7280', font: { size: 11 } },
    },
  },
}

// ── Regression: actual vs predicted scatter (sorted by actual value) ─────────
const regressionChartData = computed(() => {
  const pairs = actual.value
    .map((a, i) => ({ a, p: predicted.value[i] }))
    .filter(({ a, p }) => a != null && p != null)
    .sort((x, y) => x.a - y.a)

  return {
    labels: pairs.map((_, i) => i + 1),
    datasets: [
      {
        label: 'Actual',
        data: pairs.map(d => d.a),
        borderColor: '#60a5fa',
        backgroundColor: 'rgba(96,165,250,0.1)',
        pointRadius: pairs.length > 200 ? 0 : 2,
        tension: 0.15,
        fill: false,
      },
      {
        label: 'Predicted',
        data: pairs.map(d => d.p),
        borderColor: '#34d399',
        borderDash: [4, 3],
        pointRadius: pairs.length > 200 ? 0 : 2,
        tension: 0.15,
        fill: false,
      },
    ],
  }
})

const regressionOptions = {
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { labels: { color: '#9ca3af', usePointStyle: true, pointStyleWidth: 10 } },
    tooltip: {
      callbacks: {
        label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y?.toFixed(4) ?? '—'}`,
      },
    },
  },
  scales: {
    x: {
      ticks: { color: '#9ca3af', maxTicksLimit: 12 },
      grid:  { color: 'rgba(156,163,175,0.1)' },
      title: { display: true, text: 'Observations (sorted by actual)', color: '#6b7280', font: { size: 11 } },
    },
    y: {
      ticks: { color: '#9ca3af' },
      grid:  { color: 'rgba(156,163,175,0.1)' },
    },
  },
}

// ── Summary stats ─────────────────────────────────────────────────────────────
const classStats = computed(() => {
  if (!isClassification.value) return null
  const n = actual.value.length
  const pos = actual.value.filter(v => Math.round(v) === 1).length
  const threshold = 0.5
  let tp = 0, tn = 0, fp = 0, fn = 0
  actual.value.forEach((a, i) => {
    const pred = predicted.value[i] >= threshold ? 1 : 0
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
    { label: 'Total',     value: n },
    { label: 'Positives', value: `${pos} (${(pos / n * 100).toFixed(1)}%)` },
    { label: 'Precision', value: precision.toFixed(4) },
    { label: 'Recall',    value: recall.toFixed(4) },
    { label: 'F1',        value: f1.toFixed(4) },
  ]
})

const tableRows = computed(() =>
  actual.value.slice(0, 100).map((a, i) => {
    const p = predicted.value[i]
    if (isClassification.value) {
      return {
        index: i + 1,
        actual: Math.round(a),
        predicted: p?.toFixed(4) ?? '—',
        pred_class: p != null ? (p >= 0.5 ? 1 : 0) : '—',
        correct: (p != null && Math.round(a) === (p >= 0.5 ? 1 : 0)) ? '✓' : '✗',
      }
    }
    return {
      index: i + 1,
      actual: a?.toFixed(6) ?? '—',
      predicted: p?.toFixed(6) ?? '—',
      residual: (a != null && p != null) ? (a - p).toFixed(6) : '—',
    }
  })
)
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

      <!-- Classification: probability distribution by class -->
      <template v-if="isClassification">
        <!-- Stats strip -->
        <div class="surface-card border-round p-0" style="border: 1px solid var(--surface-border)">
          <div class="px-4 pt-3 pb-2">
            <span class="text-xs font-semibold uppercase text-color-secondary" style="letter-spacing:0.06em">
              Validation — {{ actual.length.toLocaleString() }} observations · threshold 0.5
            </span>
          </div>
          <div class="flex flex-wrap" style="gap:0">
            <div
              v-for="s in classStats" :key="s.label"
              class="flex flex-column p-4 text-center"
              style="min-width:8rem;flex:1;border-top:1px solid var(--surface-border)"
            >
              <span class="text-xl font-bold text-blue-400">{{ s.value }}</span>
              <span class="text-xs text-color-secondary mt-1">{{ s.label }}</span>
            </div>
          </div>
        </div>

        <!-- Distribution chart -->
        <div class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
          <div class="flex align-items-center justify-content-between mb-3">
            <h4 class="text-sm font-semibold m-0">Predicted Probability Distribution by Actual Class</h4>
            <span class="text-xs text-color-secondary">A good model separates the two distributions</span>
          </div>
          <div style="height: 300px">
            <Chart type="bar" :data="classDistChartData" :options="classDistOptions" class="h-full" />
          </div>
        </div>

        <!-- Table: first 100 with predicted class + correct/wrong -->
        <div class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
          <h4 class="text-sm font-semibold mb-3 m-0">
            Predictions
            <span v-if="actual.length > 100" class="text-xs font-normal text-color-secondary ml-2">(first 100 of {{ actual.length.toLocaleString() }})</span>
          </h4>
          <DataTable :value="tableRows" size="small" scrollable scrollHeight="300px" class="forecast-table">
            <Column field="index"      header="#"               style="width:4rem" />
            <Column field="actual"     header="Actual class"    style="width:8rem" />
            <Column field="predicted"  header="P(positive)"     style="font-family:monospace" />
            <Column field="pred_class" header="Predicted class" style="width:9rem" />
            <Column field="correct"    header=""                style="width:3rem;text-align:center">
              <template #body="{ data }">
                <span :style="{ color: data.correct === '✓' ? '#34d399' : '#f87171' }">{{ data.correct }}</span>
              </template>
            </Column>
          </DataTable>
        </div>
      </template>

      <!-- Regression: sorted actual vs predicted line -->
      <template v-else>
        <div class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
          <div class="flex align-items-center justify-content-between mb-3">
            <h4 class="text-sm font-semibold m-0">Actual vs Predicted — Validation Set (sorted by actual)</h4>
            <span class="text-xs text-color-secondary">{{ actual.length.toLocaleString() }} observations</span>
          </div>
          <div style="height: 360px">
            <Chart type="line" :data="regressionChartData" :options="regressionOptions" class="h-full" />
          </div>
        </div>

        <div class="surface-card border-round p-4" style="border: 1px solid var(--surface-border)">
          <h4 class="text-sm font-semibold mb-3 m-0">
            Prediction values
            <span v-if="actual.length > 100" class="text-xs font-normal text-color-secondary ml-2">(first 100 of {{ actual.length.toLocaleString() }})</span>
          </h4>
          <DataTable :value="tableRows" size="small" scrollable scrollHeight="320px" class="forecast-table">
            <Column field="index"     header="#"         style="width:4rem" />
            <Column field="actual"    header="Actual"    style="font-family:monospace" />
            <Column field="predicted" header="Predicted" style="font-family:monospace" />
            <Column field="residual"  header="Residual"  style="font-family:monospace" />
          </DataTable>
        </div>
      </template>

    </template>
  </div>
</template>

<style scoped>
.empty-state {
  text-align: center;
  padding: 3rem 1rem;
}
:deep(.forecast-table .p-datatable-thead > tr > th) {
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}
:deep(.forecast-table .p-datatable-tbody > tr > td) {
  padding: 0.35rem 0.75rem;
  font-size: 0.82rem;
  border-bottom: 1px solid var(--surface-border);
}
:deep(.forecast-table .p-datatable-tbody > tr:hover > td) {
  background: var(--surface-hover);
}
</style>
