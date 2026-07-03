<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import creditRiskAPI from '@/api/creditRiskAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import { localFetchPage } from '@/utils/tableQuery'

const router = useRouter()
const toast  = useToast()

// ── active run ────────────────────────────────────────────────────────────────
const runData     = ref(null)
const loadingRun  = ref(false)
const noActiveRun = ref(false)

// ── client selector ───────────────────────────────────────────────────────────
const clients        = ref([])
const selectedClient = ref(null)
const loadingKMV     = ref(false)

// ── KMV data ──────────────────────────────────────────────────────────────────
const kmvRows = ref([])

// ── metric selector ───────────────────────────────────────────────────────────
const METRIC_OPTIONS = [
  { label: 'PD',  value: 'PD',  title: 'PD Term Structure',   sub: 'Cumulative probability of default', pct: true  },
  { label: 'LGD', value: 'LGD', title: 'LGD Term Structure',  sub: 'Loss given default',                pct: true  },
  { label: 'DTD', value: 'DTD', title: 'Distance to Default', sub: 'Higher = safer · Merton KMV model', pct: false },
]
const selectedMetric = ref(METRIC_OPTIONS[0])

// ── chart data ────────────────────────────────────────────────────────────────
const CHART_COLORS = ['#FFE600', '#60A5FA', '#34D399', '#F472B6', '#A78BFA', '#FB923C']

function buildChartData(field) {
  const scenarios = [...new Set((kmvRows.value || []).map(r => r.SCENARIO))].filter(Boolean)
  const allYears  = [...new Set((kmvRows.value || []).map(r => r.YEAR))].sort()
  return {
    labels: allYears,
    datasets: scenarios.map((scen, i) => {
      const rows   = kmvRows.value.filter(r => r.SCENARIO === scen)
      const byYear = Object.fromEntries(rows.map(r => [r.YEAR, r]))
      return {
        label: scen,
        data: allYears.map(y => byYear[y]?.[field] ?? null),
        borderColor: CHART_COLORS[i % CHART_COLORS.length],
        backgroundColor: 'transparent',
        borderWidth: 2,
        tension: 0.3,
        pointRadius: 3,
        pointHoverRadius: 5,
      }
    }),
  }
}

const activeChartData = computed(() => buildChartData(selectedMetric.value.value))

const pctOptions = {
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${(ctx.parsed.y * 100).toFixed(2)}%` } } },
  interaction: { mode: 'nearest', axis: 'x', intersect: false },
  scales: {
    x: { ticks: { color: '#9ca3af', font: { size: 10 } }, grid: { display: false } },
    y: {
      ticks: { color: '#9ca3af', font: { size: 10 }, callback: v => (v * 100).toFixed(1) + '%' },
      grid: { color: 'rgba(156,163,175,0.08)' },
      border: { display: false },
    },
  },
}

const rawOptions = {
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
  interaction: { mode: 'nearest', axis: 'x', intersect: false },
  scales: {
    x: { ticks: { color: '#9ca3af', font: { size: 10 } }, grid: { display: false } },
    y: { ticks: { color: '#9ca3af', font: { size: 10 } }, grid: { color: 'rgba(156,163,175,0.08)' }, border: { display: false } },
  },
}

const activeChartOptions = computed(() => selectedMetric.value.pct ? pctOptions : rawOptions)

const legendItems = computed(() =>
  (activeChartData.value.datasets || []).map((d, i) => ({ label: d.label, color: CHART_COLORS[i % CHART_COLORS.length] }))
)

// ── data loading ──────────────────────────────────────────────────────────────
onMounted(async () => {
  loadingRun.value = true
  try {
    const { data } = await creditRiskAPI.getActiveRun()
    runData.value = data
    clients.value = data.client_ids ?? []
    if (clients.value.length) selectedClient.value = clients.value[0]
    noActiveRun.value = false
  } catch (e) {
    if (e?.response?.status === 404) {
      noActiveRun.value = true
    } else {
      toast.add({ severity: 'error', summary: 'Failed to load active run', detail: e?.response?.data?.error ?? e.message, life: 4000 })
    }
  } finally {
    loadingRun.value = false
  }
})

watch(selectedClient, (v) => { if (v && runData.value) fetchKMV() })

async function fetchKMV() {
  if (!runData.value?.run_id || !selectedClient.value) return
  loadingKMV.value = true
  kmvRows.value    = []
  try {
    const { data } = await creditRiskAPI.getClientResult(runData.value.run_id, selectedClient.value)
    kmvRows.value = data.kmv ?? []
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load results', detail: e?.response?.data?.error ?? e.message, life: 5000 })
  } finally {
    loadingKMV.value = false
  }
}

function pct(v) { return v != null && isFinite(v) ? (v * 100).toFixed(2) + '%' : '—' }
function num(v) { return v != null && isFinite(v) ? Number(v).toFixed(4) : '—' }

const kmvTableColumns = [
  { field: 'YEAR', header: 'Year', width: '7rem' },
  { field: 'SCENARIO', header: 'Scenario', width: '9rem' },
  { field: 'Rating', header: 'Rating', width: '7rem' },
  { field: 'PD', header: 'PD', width: '8rem', formatter: (v) => pct(v) },
  { field: 'Marginal PD', header: 'Marginal PD', width: '9rem', formatter: (v) => pct(v) },
  { field: 'LGD', header: 'LGD', width: '8rem', formatter: (v) => pct(v) },
  { field: 'DTD', header: 'DTD', width: '7rem', formatter: (v) => num(v) },
]
const kmvFetchPage = localFetchPage(() => kmvRows.value)
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 1400px">
    <!-- Header -->
    <header class="flex align-items-end justify-content-between mb-5 flex-wrap gap-3">
      <div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">PD / LGD Term Structure</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">KMV-derived probability of default, loss given default, and distance to default.</p>
      </div>
      <div class="flex align-items-center gap-3 flex-wrap">
        <div class="flex flex-column gap-1">
          <span class="text-xs text-color-secondary uppercase tracking-wide">Metric</span>
          <Dropdown
            v-model="selectedMetric"
            :options="METRIC_OPTIONS"
            option-label="label"
            class="w-8rem"
          />
        </div>
        <div class="flex flex-column gap-1">
          <span class="text-xs text-color-secondary uppercase tracking-wide">Client</span>
          <Dropdown
            v-model="selectedClient"
            :options="clients"
            :loading="loadingRun"
            :disabled="!clients.length"
            placeholder="Select client"
            class="w-12rem"
          />
        </div>
      </div>
    </header>

    <!-- No active run -->
    <div v-if="noActiveRun && !loadingRun" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-chart-bar text-4xl text-color-secondary opacity-50" />
      <div class="text-center">
        <div class="text-sm font-medium mb-1">No active analysis run</div>
        <div class="text-xs text-color-secondary">Set an active run in Analysis Jobs to view PD / LGD results.</div>
      </div>
      <Button label="Analysis Jobs" icon="pi pi-list" size="small" @click="router.push({ name: 'credit_risk_jobs' })" />
    </div>

    <!-- Loading -->
    <div v-else-if="loadingKMV || loadingRun" class="flex justify-content-center align-items-center" style="height: 12rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <template v-else-if="kmvRows.length">
      <!-- Full-width chart -->
      <div class="panel mb-4">
        <div class="panel-head">
          <div>
            <div class="panel-title">{{ selectedMetric.title }}</div>
            <div class="text-xs text-color-secondary mt-1">{{ selectedMetric.sub }}</div>
          </div>
          <div class="legend-row">
            <span v-for="l in legendItems" :key="l.label" class="legend-pill">
              <span class="legend-dot" :style="{ background: l.color }" />
              {{ l.label }}
            </span>
          </div>
        </div>
        <div style="height: 280px">
          <Chart type="line" :data="activeChartData" :options="activeChartOptions" class="h-full" />
        </div>
      </div>

      <!-- Summary table -->
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">KMV detail</span>
          <span class="text-xs text-color-secondary">{{ kmvRows.length }} rows · client {{ selectedClient }}</span>
        </div>
        <div class="bare-table">
          <CommonDataTable
            :key="selectedClient"
            :columns="kmvTableColumns"
            :fetch-page="kmvFetchPage"
            :initial-page-size="500"
            empty-message="No KMV rows for this client."
          />
        </div>
      </div>
    </template>

    <div v-else-if="!loadingKMV && selectedClient" class="panel flex align-items-center justify-content-center gap-3" style="height: 12rem">
      <i class="pi pi-chart-line text-3xl text-color-secondary" />
      <div>
        <div class="text-sm font-medium">No KMV data</div>
        <div class="text-xs text-color-secondary">Select a client to load results.</div>
      </div>
    </div>


  </div>
</template>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.25rem 1.25rem 1rem;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
.panel-title {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

.legend-row  { display: flex; flex-wrap: wrap; gap: 6px; }
.legend-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-ground);
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}
.legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; display: inline-block; }

.bare-table { margin: 0 -1.25rem -1rem; }
</style>
