<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import creditRiskAPI from '@/api/creditRiskAPI'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()
const toast  = useToast()

const METRICS = [
  { key: 'revenue_growth', label: 'Revenue growth' },
  { key: 'cogs_margin',    label: 'COGS / Revenue' },
  { key: 'leverage',       label: 'Net debt / EBITDA' },
]
const selectedMetric = ref(METRICS[0].key)

const loading      = ref(false)
const noActiveRun  = ref(false)
const errorMessage = ref(null)
const drilledSector = ref(null)

// Company drill-down is opt-in: picking a sector shows a company multi-select +
// Confirm, and only the chosen companies are computed/plotted (the per-company
// series is the expensive part, so we never compute the whole sector at once).
const companiesBySector = ref({})
const selectedCompanies = ref([])
const appliedCompanies  = ref([])

const heat = ref(null) // { metric, label, unit, years, drilled, title, subtitle, rows }

const sectorCompanies = computed(() => companiesBySector.value[drilledSector.value] || [])

function heatCell(v) {
  if (v == null) return { txt: '—', bg: 'var(--surface-ground)', color: 'var(--text-color-muted)' }
  if (v >= 0) {
    const a = Math.min(0.10 + v / 9 * 0.85, 0.95)
    return { txt: '+' + v.toFixed(1), bg: `rgba(255,214,0,${a.toFixed(2)})`, color: '#1A1A24' }
  }
  const a = Math.min(0.08 + Math.abs(v) / 9 * 0.8, 0.9)
  return { txt: '−' + Math.abs(v).toFixed(1), bg: `rgba(46,46,56,${a.toFixed(2)})`, color: a > 0.45 ? '#FFFFFF' : '#1A1A24' }
}

async function fetchMeta() {
  try {
    const { data } = await creditRiskAPI.analysisMeta()
    companiesBySector.value = data.companies_by_sector ?? {}
  } catch { /* meta is best-effort; drill-down falls back to sector companies from the heatmap */ }
}

async function fetchHeatmap() {
  loading.value = true
  errorMessage.value = null
  try {
    const params = { metric: selectedMetric.value }
    if (drilledSector.value) {
      params.sector = drilledSector.value
      params.clients = appliedCompanies.value.join(',')
    }
    const { data } = await creditRiskAPI.analysisHeatmap(params)
    heat.value = data
    noActiveRun.value = false
  } catch (e) {
    heat.value = null
    if (e?.response?.status === 404) {
      noActiveRun.value = true
    } else {
      errorMessage.value = e?.response?.data?.error ?? e.message
    }
  } finally {
    loading.value = false
  }
}

function selectMetric(key) {
  selectedMetric.value = key
}

function drillInto(sector) {
  drilledSector.value = sector
  // Default the picker to the sector's companies but don't plot until confirmed.
  selectedCompanies.value = [...(companiesBySector.value[sector] || [])]
  appliedCompanies.value = []
  heat.value = null
}

function confirmCompanies() {
  if (!selectedCompanies.value.length) {
    toast.add({ severity: 'warn', summary: 'Select at least one company', life: 2500 })
    return
  }
  appliedCompanies.value = [...selectedCompanies.value]
  fetchHeatmap()
}

function backToSectors() {
  drilledSector.value = null
  selectedCompanies.value = []
  appliedCompanies.value = []
  fetchHeatmap()
}

// Metric change: re-fetch sector view immediately, or re-fetch drill-down only if
// companies are already applied (don't auto-compute before the user confirms).
watch(selectedMetric, () => {
  if (drilledSector.value && !appliedCompanies.value.length) return
  fetchHeatmap()
})

onMounted(async () => {
  await Promise.all([fetchMeta(), fetchHeatmap()])
})
</script>

<template>
  <div>
    <div v-if="drilledSector" class="back-link" @click="backToSectors">&larr; All sectors</div>

    <PageHeader
      eyebrow="ANALYSIS"
      :title="drilledSector ? drilledSector : (heat?.title ?? 'Sector Heatmap')"
      :subtitle="drilledSector ? 'Company-level detail — select companies to plot' : (heat?.subtitle ?? 'Forecasted change by sector and year')"
    >
      <template #actions>
        <div class="legend-row">
          <span class="legend-item"><span class="legend-swatch" style="background: rgba(46,46,56,0.75)" />Decline</span>
          <span class="legend-item"><span class="legend-swatch" style="background: rgba(255,214,0,0.85)" />Growth</span>
        </div>
      </template>
    </PageHeader>

    <div class="metric-row">
      <span class="metric-label">METRIC</span>
      <div
        v-for="m in METRICS"
        :key="m.key"
        class="metric-chip"
        :class="{ active: selectedMetric === m.key }"
        @click="selectMetric(m.key)"
      >{{ m.label }}</div>
      <span class="font-mono unit-caption">{{ heat?.unit ?? '' }}</span>
    </div>

    <!-- Company picker (drill-down only) -->
    <div v-if="drilledSector" class="company-bar">
      <span class="metric-label">COMPANIES</span>
      <MultiSelect
        v-model="selectedCompanies"
        :options="sectorCompanies"
        filter
        placeholder="Select companies"
        :maxSelectedLabels="3"
        selectedItemsLabel="{0} companies selected"
        class="company-select font-mono"
        style="min-width: 22rem"
      />
      <Button label="Confirm" icon="pi pi-check" size="small" @click="confirmCompanies" />
      <span class="company-hint">{{ sectorCompanies.length }} companies in {{ drilledSector }}</span>
    </div>

    <!-- No active run -->
    <div v-if="noActiveRun && !loading" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-th-large text-4xl text-color-secondary opacity-50" />
      <div class="text-center">
        <div class="text-sm font-medium mb-1">No active analysis run</div>
        <div class="text-xs text-color-secondary">Set an active run in Job History to view the Sector Heatmap.</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Missing revenue/COGS forecast inputs -->
    <div v-else-if="errorMessage && !loading" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-exclamation-circle text-4xl text-color-secondary opacity-50" />
      <div class="text-center" style="max-width: 28rem">
        <div class="text-sm font-medium mb-1">Heatmap data unavailable</div>
        <div class="text-xs text-color-secondary">{{ errorMessage }}</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="flex justify-content-center align-items-center" style="height: 12rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <!-- Drill-down: awaiting company selection -->
    <div v-else-if="drilledSector && !appliedCompanies.length" class="panel flex flex-column align-items-center justify-content-center gap-2" style="height: 16rem">
      <i class="pi pi-building text-3xl text-color-secondary opacity-50" />
      <div class="text-sm font-medium">Select companies and press Confirm</div>
      <div class="text-xs text-color-secondary">Only the chosen companies are computed, keeping the view fast.</div>
    </div>

    <div v-else-if="heat" class="panel">
      <div class="matrix-grid matrix-grid--head">
        <div>{{ heat.drilled ? 'COMPANY' : 'SECTOR' }}</div>
        <div v-for="y in heat.years" :key="y" class="ta-center">{{ y }}</div>
      </div>
      <div v-for="row in heat.rows" :key="row.key" class="matrix-grid matrix-grid--row">
        <div
          class="row-label"
          :class="{ clickable: row.drillable }"
          @click="row.drillable && drillInto(row.key)"
        >
          <span :class="{ 'font-mono': !row.drillable }">{{ row.label }}</span>
          <span v-if="row.drillable" class="row-arrow">&rsaquo;</span>
        </div>
        <div
          v-for="(v, i) in row.values" :key="i"
          class="font-mono cell"
          :style="{ background: heatCell(v).bg, color: heatCell(v).color }"
        >{{ heatCell(v).txt }}</div>
      </div>
      <div v-if="!heat.drilled" class="footer-caption">Click a sector to view company-level detail</div>
    </div>
  </div>
</template>

<style scoped>
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-color-muted);
  cursor: pointer;
  margin-bottom: 14px;
}
.back-link:hover { color: var(--text-color); }

.legend-row { display: flex; align-items: center; gap: 14px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-color-secondary); }
.legend-swatch { width: 14px; height: 14px; display: inline-block; border-radius: 2px; }

.metric-row { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.metric-label { font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-color-muted); }
.metric-chip {
  padding: 7px 12px;
  border-radius: 2px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--surface-border-input);
  background: #FFFFFF;
  color: var(--text-color-secondary);
}
.metric-chip:hover { border-color: var(--ink); }
.metric-chip.active { background: var(--ink); color: #FFFFFF; border-color: var(--ink); }
.unit-caption { font-size: 11.5px; color: var(--text-color-muted); }

.company-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 12px 14px;
  background: var(--surface-inset);
  border-radius: 2px;
}
.company-hint { font-size: 11.5px; color: var(--text-color-muted); }

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 14px 16px;
}

.matrix-grid {
  display: grid;
  grid-template-columns: 230px repeat(v-bind('heat?.years.length || 5'), 1fr);
  column-gap: 8px;
  align-items: center;
}
.matrix-grid--head {
  padding-bottom: 9px;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  color: var(--text-color-muted);
}
.ta-center { text-align: center; font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600; }
.row-label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; padding: 4px 0; }
.row-label.clickable { cursor: pointer; }
.row-label.clickable:hover { color: var(--ink); }
.row-arrow { color: var(--text-color-muted); font-weight: 400; }
.cell {
  margin: 2px 0;
  padding: 11px 0;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  border-radius: 2px;
}
.footer-caption { font-size: 12px; color: var(--text-color-muted); padding-top: 12px; }
</style>
