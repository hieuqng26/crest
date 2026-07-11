<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import creditRiskAPI from '@/api/creditRiskAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import { localFetchPage } from '@/utils/tableQuery'
import { scenarioStyle } from '@/utils/chartTheme'
import LinePlot from '@/components/charts/LinePlot.vue'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()
const toast  = useToast()

// ── active run ────────────────────────────────────────────────────────────────
const runData     = ref(null)
const loadingRun  = ref(false)
const noActiveRun = ref(false)

// ── sector / client selector ─────────────────────────────────────────────────
// Sector→client mapping is sourced from the analysis series (same materialised
// data the Financial Forecast page uses) — best-effort: if it isn't ready yet
// the sector filter just stays empty and the client list is unfiltered.
const clients          = ref([])
const sectors          = ref([])
const companiesBySector = ref({})
const selectedSector   = ref(null) // null = all sectors
const selectedClient   = ref(null)
const loadingKMV       = ref(false)

const clientOptions = computed(() => {
  if (!selectedSector.value) return clients.value
  const inSector = new Set(companiesBySector.value[selectedSector.value] ?? [])
  return clients.value.filter((c) => inSector.has(c))
})

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
function buildSeries(field) {
  const scenarios = [...new Set((kmvRows.value || []).map(r => r.SCENARIO))].filter(Boolean)
  const allYears  = [...new Set((kmvRows.value || []).map(r => r.YEAR))].sort()
  let fallbackIdx = 0
  return scenarios.map((scen) => {
    const byYear = Object.fromEntries(kmvRows.value.filter(r => r.SCENARIO === scen).map(r => [r.YEAR, r]))
    const st = scenarioStyle(scen, fallbackIdx++)
    return {
      name: scen,
      x: allYears,
      y: allYears.map(y => byYear[y]?.[field] ?? null),
      color: st.color,
      width: st.width,
      dash: st.dash,
    }
  })
}

const activeSeries = computed(() => buildSeries(selectedMetric.value.value))

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

  // Sector filter is best-effort — a 202 (still materialising) or any error
  // just leaves it empty; the client dropdown keeps working unfiltered.
  try {
    const { data } = await creditRiskAPI.analysisMeta()
    sectors.value = data.sectors ?? []
    companiesBySector.value = data.companies_by_sector ?? {}
  } catch {
    sectors.value = []
    companiesBySector.value = {}
  }
})

watch(selectedSector, () => {
  if (selectedClient.value && !clientOptions.value.includes(selectedClient.value)) {
    selectedClient.value = clientOptions.value[0] ?? null
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
          <span class="field-label">Sector</span>
          <EySelect
            v-model="selectedSector"
            :options="[null, ...sectors]"
            :optionLabel="v => v ?? 'All sectors'"
            placeholder="All sectors"
            :disabled="!sectors.length"
            showClear
            style="width: 12rem"
          />
        </div>
        <div class="field-col">
          <span class="field-label">Client</span>
          <EySelect
            v-model="selectedClient"
            :options="clientOptions"
            :loading="loadingRun"
            :disabled="!clientOptions.length"
            placeholder="Select client"
            class="font-mono"
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
        </div>
        <LinePlot
          :series="activeSeries"
          :height="420"
          :y-tick-format="selectedMetric.pct ? '.1%' : ''"
          :y-hover-format="selectedMetric.pct ? '.2%' : '.4f'"
          markers
          :png-filename="`pd-lgd-${selectedMetric.value.toLowerCase()}`"
        />
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

.bare-table { margin: 0 -1.25rem -1rem; }

.field-col { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }
</style>
