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
const runData        = ref(null)   // active run object (includes client_ids, exposure)
const loadingRun     = ref(false)
const noActiveRun    = ref(false)

// ── sector / client selector ─────────────────────────────────────────────────
// Sector→client mapping is sourced from the analysis series (same materialised
// data the Financial Forecast page uses) — best-effort: if it isn't ready yet
// the sector filter just stays empty and the client list is unfiltered.
const clients          = ref([])
const sectors          = ref([])
const companiesBySector = ref({})
const selectedSector   = ref(null) // null = all sectors
const selectedClient   = ref(null)
const loadingECL       = ref(false)

const clientOptions = computed(() => {
  if (!selectedSector.value) return clients.value
  const inSector = new Set(companiesBySector.value[selectedSector.value] ?? [])
  return clients.value.filter((c) => inSector.has(c))
})

// ── ECL data ──────────────────────────────────────────────────────────────────
const eclRows = ref([])

// ── KPI strip ─────────────────────────────────────────────────────────────────
const kpis = computed(() => {
  const rows = eclRows.value
  if (!rows.length) return []
  const maxEcl12   = Math.max(...rows.map(r => r.ECL_12M || 0))
  const maxEclLife = Math.max(...rows.map(r => r.ECL_Lifetime || 0))
  const ead        = runData.value?.exposure ?? 0
  const coverage   = ead > 0 ? (maxEclLife / ead * 100).toFixed(2) + '%' : '—'
  return [
    { label: '12-Month ECL',   value: fmt(maxEcl12),   sub: 'peak single-year' },
    { label: 'Lifetime ECL',   value: fmt(maxEclLife), sub: 'peak cumulative' },
    { label: 'Coverage Ratio', value: coverage,        sub: 'ECL / EAD' },
  ]
})

function fmt(v) {
  if (v == null || !isFinite(v)) return '—'
  if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(2) + 'B'
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  return v.toFixed(2)
}

// ── chart data ────────────────────────────────────────────────────────────────
// Scenario → line style comes from the shared token-driven chart theme.
function buildEclSeries(field) {
  const scenarios = [...new Set((eclRows.value || []).map(r => r.SCENARIO))].filter(Boolean)
  const allYears  = [...new Set((eclRows.value || []).map(r => r.YEAR))].sort()
  let fallbackIdx = 0
  return scenarios.map((scen) => {
    const byYear = Object.fromEntries(eclRows.value.filter(r => r.SCENARIO === scen).map(r => [r.YEAR, r]))
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

const eclSeries   = computed(() => buildEclSeries('ECL_Lifetime'))
const ecl12Series = computed(() => buildEclSeries('ECL_12M'))

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

watch(selectedClient, (v) => {
  if (v && runData.value) fetchECL()
})

const eclTableColumns = [
  { field: 'YEAR', header: 'Year', width: '7rem' },
  { field: 'SCENARIO', header: 'Scenario', width: '9rem' },
  { field: 'ECL_12M', header: '12M ECL', width: '9rem', formatter: (v) => fmt(v) },
  { field: 'ECL_Lifetime', header: 'Lifetime ECL', width: '9rem', formatter: (v) => fmt(v) },
]
const eclFetchPage = localFetchPage(() => eclRows.value)

async function fetchECL() {
  if (!runData.value?.run_id || !selectedClient.value) return
  loadingECL.value = true
  eclRows.value    = []
  try {
    const { data } = await creditRiskAPI.getClientResult(runData.value.run_id, selectedClient.value)
    eclRows.value = data.ecl ?? []
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load results', detail: e?.response?.data?.error ?? e.message, life: 5000 })
  } finally {
    loadingECL.value = false
  }
}
</script>

<template>
  <div>
    <PageHeader eyebrow="ANALYSIS" title="IFRS 9 ECL" subtitle="Expected credit losses by scenario and horizon.">
      <template #actions>
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
        <div class="text-xs text-color-secondary">Set an active run in Job History to view ECL results.</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Loading -->
    <div v-else-if="loadingRun || loadingECL" class="flex justify-content-center align-items-center" style="height: 12rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <template v-else-if="eclRows.length">
      <!-- KPI strip -->
      <div class="stat-strip mb-4">
        <div v-for="k in kpis" :key="k.label" class="stat-cell">
          <div class="text-color-secondary text-xs uppercase tracking-wide mb-1">{{ k.label }}</div>
          <div class="text-2xl font-semibold tracking-tight">{{ k.value }}</div>
          <div class="text-xs text-color-secondary mt-1">{{ k.sub }}</div>
        </div>
      </div>

      <!-- Charts row -->
      <div class="flex flex-column gap-4 mb-4">
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">Lifetime ECL</div>
              <div class="text-xs text-color-secondary mt-1">Per year · all scenarios</div>
            </div>
          </div>
          <LinePlot
            :series="eclSeries"
            :height="360"
            y-tick-format=".2s"
            y-hover-format=".3s"
            markers
            png-filename="ecl-lifetime"
          />
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">12-Month ECL</div>
              <div class="text-xs text-color-secondary mt-1">Per year · all scenarios</div>
            </div>
          </div>
          <LinePlot
            :series="ecl12Series"
            :height="360"
            y-tick-format=".2s"
            y-hover-format=".3s"
            markers
            png-filename="ecl-12m"
          />
        </div>
      </div>

      <!-- Detail table -->
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">ECL detail</span>
          <span class="text-xs text-color-secondary">{{ eclRows.length }} rows · client {{ selectedClient }}</span>
        </div>
        <div class="bare-table">
          <CommonDataTable
            :key="selectedClient"
            :columns="eclTableColumns"
            :fetch-page="eclFetchPage"
            :initial-page-size="500"
            empty-message="No ECL rows for this client."
          />
        </div>
      </div>
    </template>

    <div v-else-if="!loadingECL && selectedClient" class="panel flex align-items-center justify-content-center gap-3" style="height: 12rem">
      <i class="pi pi-chart-line text-3xl text-color-secondary" />
      <div>
        <div class="text-sm font-medium">No ECL data</div>
        <div class="text-xs text-color-secondary">Select a client to load results.</div>
      </div>
    </div>

    <Toast />
  </div>
</template>

<style scoped>
.stat-strip {
  display: flex;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-top: 3px solid var(--ink);
  border-radius: 2px;
  overflow: hidden;
}
.stat-cell {
  flex: 1;
  padding: 1rem 1.25rem;
}
.stat-cell + .stat-cell { border-left: 1px solid var(--surface-border-row); }

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
