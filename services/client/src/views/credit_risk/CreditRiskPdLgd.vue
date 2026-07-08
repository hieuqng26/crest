<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import creditRiskAPI from '@/api/creditRiskAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import { localFetchPage } from '@/utils/tableQuery'
import { scenarioLineStyles, fallbackSeriesColors, axisDefaults } from '@/utils/chartTheme'
import PageHeader from '@/components/ui/PageHeader.vue'

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
// Scenario → line style comes from the shared token-driven chart theme.
function buildChartData(field) {
  const scenarioStyle = scenarioLineStyles()
  const fallbackColors = fallbackSeriesColors()
  const scenarios = [...new Set((kmvRows.value || []).map(r => r.SCENARIO))].filter(Boolean)
  const allYears  = [...new Set((kmvRows.value || []).map(r => r.YEAR))].sort()
  let fallbackIdx = 0
  return {
    labels: allYears,
    datasets: scenarios.map((scen) => {
      const rows   = kmvRows.value.filter(r => r.SCENARIO === scen)
      const byYear = Object.fromEntries(rows.map(r => [r.YEAR, r]))
      const style = scenarioStyle[scen] ?? { color: fallbackColors[fallbackIdx++ % fallbackColors.length], width: 2, dash: [] }
      return {
        label: scen,
        data: allYears.map(y => byYear[y]?.[field] ?? null),
        borderColor: style.color,
        backgroundColor: 'transparent',
        borderWidth: style.width,
        borderDash: style.dash,
        tension: 0.3,
        pointRadius: 3,
        pointHoverRadius: 5,
      }
    }),
  }
}

const activeChartData = computed(() => buildChartData(selectedMetric.value.value))

function buildChartOptions(pct) {
  const scales = axisDefaults()
  if (pct) scales.y.ticks.callback = (v) => (v * 100).toFixed(1) + '%'
  return {
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        mode: 'index',
        intersect: false,
        ...(pct && { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${(ctx.parsed.y * 100).toFixed(2)}%` } }),
      },
    },
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    scales,
  }
}

const activeChartOptions = computed(() => buildChartOptions(selectedMetric.value.pct))

const legendItems = computed(() =>
  (activeChartData.value.datasets || []).map((d) => ({ label: d.label, color: d.borderColor }))
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
  <div>
    <PageHeader eyebrow="ANALYSIS" title="PD / LGD Term Structure" subtitle="KMV-derived probability of default, loss given default, and distance to default.">
      <template #actions>
        <div class="field-col">
          <span class="field-label">Metric</span>
          <EySelect
            v-model="selectedMetric"
            :options="METRIC_OPTIONS"
            optionLabel="label"
            style="width: 8rem"
          />
        </div>
        <div class="field-col">
          <span class="field-label">Client</span>
          <EySelect
            v-model="selectedClient"
            :options="clients"
            :loading="loadingRun"
            :disabled="!clients.length"
            placeholder="Select client"
            style="width: 12rem"
          />
        </div>
      </template>
    </PageHeader>

    <!-- No active run -->
    <div v-if="noActiveRun && !loadingRun" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-chart-bar text-4xl text-color-secondary opacity-50" />
      <div class="text-center">
        <div class="text-sm font-medium mb-1">No active analysis run</div>
        <div class="text-xs text-color-secondary">Set an active run in Job History to view PD / LGD results.</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
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
  border-radius: 2px;
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
  border-radius: 2px;
  background: var(--surface-ground);
  font-size: 0.75rem;
  color: var(--text-color-secondary);
}
.legend-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; display: inline-block; }

.bare-table { margin: 0 -1.25rem -1rem; }

.field-col { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }
</style>
