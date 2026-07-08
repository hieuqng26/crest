<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import creditRiskAPI from '@/api/creditRiskAPI'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()

const loading      = ref(false)
const noActiveRun  = ref(false)
const errorMessage = ref(null)

const sectors           = ref([])
const companiesBySector = ref({})
const selectedSector     = ref(null)
const selectedCompany    = ref(null)

const forecastTargets = ref([])          // [{ key, title }] from meta
const selectedTargets = ref([])          // array of slot keys

const companyOptions = computed(() => (companiesBySector.value[selectedSector.value] || []))

const forecastData = ref(null) // { sector, client_id, metrics: [...] }

async function fetchMeta() {
  loading.value = true
  try {
    const { data } = await creditRiskAPI.analysisMeta()
    sectors.value = data.sectors ?? []
    companiesBySector.value = data.companies_by_sector ?? {}
    forecastTargets.value = data.forecast_targets ?? []
    selectedTargets.value = forecastTargets.value.map((t) => t.key)
    if (sectors.value.length) selectedSector.value = sectors.value[0]
    noActiveRun.value = false
  } catch (e) {
    if (e?.response?.status === 404) noActiveRun.value = true
    else errorMessage.value = e?.response?.data?.error ?? e.message
  } finally {
    loading.value = false
  }
}

async function fetchForecast() {
  if (!selectedSector.value) return
  if (!selectedTargets.value.length) { forecastData.value = { metrics: [] }; return }
  loading.value = true
  errorMessage.value = null
  try {
    const { data } = await creditRiskAPI.analysisForecast({
      sector: selectedSector.value,
      client_id: selectedCompany.value || undefined,
      targets: selectedTargets.value.join(','),
    })
    forecastData.value = data
  } catch (e) {
    forecastData.value = null
    errorMessage.value = e?.response?.data?.error ?? e.message
  } finally {
    loading.value = false
  }
}

watch(selectedSector, () => { selectedCompany.value = null; fetchForecast() })
watch(selectedCompany, fetchForecast)
watch(selectedTargets, fetchForecast)

onMounted(async () => {
  await fetchMeta()
  if (selectedSector.value) await fetchForecast()
})

// ── chart styling ──────────────────────────────────────────────────────────────
const HISTORY_COLOR = '#2E2E38'
const SCENARIO_STYLE = {
  Baseline: { color: '#E8C400', width: 2.8, dash: 0 },
  Adverse: { color: '#9B9BA6', width: 1.8, dash: 0 },
  'Severely Adverse': { color: '#9B9BA6', width: 1.8, dash: 6 },
}
const scenarioStyle = (name) => SCENARIO_STYLE[name] ?? { color: '#2D6FD6', width: 1.8, dash: 0 }

// Legend/scenario visibility is shared across every card: clicking a legend item
// hides that scenario on all charts at once.
const hiddenScenarios = ref(new Set())
const toggleScenario = (name) => {
  const s = new Set(hiddenScenarios.value)
  if (s.has(name)) s.delete(name)
  else s.add(name)
  hiddenScenarios.value = s
}
const isHidden = (name) => hiddenScenarios.value.has(name)

const compactFmt = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
const fmtNum = (v) => (v == null ? '—' : compactFmt.format(v))

// Which scenario names appear anywhere in the current payload (for the legend).
const scenarioNames = computed(() => {
  const names = new Set()
  for (const m of forecastData.value?.metrics || []) {
    for (const n of Object.keys(m.scenarios || {})) names.add(n)
  }
  const order = { Baseline: 0, Adverse: 1, 'Severely Adverse': 2 }
  return [...names].sort((a, b) => (order[a] ?? 99) - (order[b] ?? 99))
})

function buildCard(metric) {
  if (!metric.available) return { ...metric, unavailable: true }

  const hist = metric.history || []
  const scenarioEntries = Object.entries(metric.scenarios || {})
  if (!hist.length && !scenarioEntries.length) return { ...metric, unavailable: true }

  const lastHist = hist.length ? hist[hist.length - 1] : null
  const splitYear = lastHist ? lastHist.year : null

  const series = []
  const widths = []
  const dashes = []
  const colors = []

  if (hist.length) {
    series.push({ name: 'History', data: hist.map((p) => ({ x: p.year, y: p.value })) })
    widths.push(1.8)
    dashes.push(0)
    colors.push(HISTORY_COLOR)
  }

  for (const [name, pts] of scenarioEntries) {
    if (isHidden(name)) continue
    const st = scenarioStyle(name)
    // Prepend history's last point so the forecast path joins continuously
    // (this is what removes the visual "jump" at the history→forecast boundary).
    const data = (lastHist ? [{ x: lastHist.year, y: lastHist.value }] : []).concat(
      pts.map((p) => ({ x: p.year, y: p.value }))
    )
    series.push({ name, data })
    widths.push(st.width)
    dashes.push(st.dash)
    colors.push(st.color)
  }

  const allYears = [
    ...hist.map((p) => p.year),
    ...scenarioEntries.flatMap(([, pts]) => pts.map((p) => p.year)),
  ]
  const minYear = allYears.length ? Math.min(...allYears) : 0
  const maxYear = allYears.length ? Math.max(...allYears) : 0

  const options = {
    chart: {
      type: 'line',
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
      fontFamily: 'inherit',
      parentHeightOffset: 0,
    },
    colors,
    stroke: { curve: 'straight', width: widths, dashArray: dashes },
    legend: { show: false },
    grid: {
      borderColor: '#F0F0F3',
      strokeDashArray: 0,
      xaxis: { lines: { show: false } },
      padding: { left: 8, right: 12, top: 0, bottom: 0 },
    },
    markers: { size: 0, hover: { size: 4 } },
    xaxis: {
      type: 'numeric',
      min: minYear,
      max: maxYear,
      tickAmount: Math.min(8, Math.max(1, maxYear - minYear)),
      decimalsInFloat: 0,
      labels: {
        formatter: (v) => (v == null ? '' : String(Math.round(v))),
        style: { colors: '#9B9BA6', fontFamily: 'IBM Plex Mono, monospace', fontSize: '10px' },
      },
      axisBorder: { show: false },
      axisTicks: { show: false },
      crosshairs: { show: true, stroke: { color: '#D8D8DE', width: 1, dashArray: 3 } },
      tooltip: { enabled: false },
    },
    yaxis: {
      labels: {
        formatter: (v) => fmtNum(v),
        style: { colors: '#9B9BA6', fontFamily: 'IBM Plex Mono, monospace', fontSize: '10px' },
      },
    },
    tooltip: {
      shared: true,
      intersect: false,
      x: { formatter: (v) => String(Math.round(v)) },
      y: { formatter: (v) => (v == null ? '—' : fmtNum(v)) },
    },
    annotations: splitYear != null ? {
      xaxis: [{
        x: splitYear,
        strokeDashArray: 4,
        borderColor: '#D8D8DE',
        label: {
          text: 'Forecast →',
          orientation: 'horizontal',
          position: 'top',
          offsetY: -4,
          style: {
            color: '#9B9BA6',
            background: 'transparent',
            fontFamily: 'IBM Plex Mono, monospace',
            fontSize: '9px',
          },
        },
      }],
    } : {},
  }

  return { ...metric, unavailable: false, series, options }
}

const cards = computed(() => (forecastData.value?.metrics || []).map(buildCard))
const singleTarget = computed(() => selectedTargets.value.length === 1)
</script>

<template>
  <div>
    <PageHeader eyebrow="ANALYSIS" title="Financial Forecast" subtitle="Model forecasts per financial item — history and three scenario paths.">
      <template #actions>
        <div class="field-col">
          <span class="field-label">Sector</span>
          <EySelect
            v-model="selectedSector"
            :options="sectors"
            placeholder="Select sector"
            :disabled="!sectors.length"
            style="width: 12rem"
          />
        </div>
        <div class="field-col">
          <span class="field-label">Company</span>
          <EySelect
            v-model="selectedCompany"
            :options="companyOptions"
            placeholder="All companies"
            :disabled="!companyOptions.length"
            showClear
            class="font-mono"
            style="width: 12rem"
          />
        </div>
        <div class="field-col">
          <span class="field-label">Targets</span>
          <EySelect
            v-model="selectedTargets"
            :options="forecastTargets"
            optionLabel="title"
            optionValue="key"
            multiple
            showToggleAll
            filter
            :disabled="!forecastTargets.length"
            style="width: 14rem"
          />
        </div>
      </template>
    </PageHeader>

    <!-- No active run -->
    <div v-if="noActiveRun && !loading" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-chart-line text-4xl text-color-secondary opacity-50" />
      <div class="text-center">
        <div class="text-sm font-medium mb-1">No active analysis run</div>
        <div class="text-xs text-color-secondary">Set an active run in Job History to view the Financial Forecast.</div>
      </div>
      <Button label="Job History" icon="pi pi-list" size="small" @click="router.push({ name: 'jobs_history' })" />
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="flex justify-content-center align-items-center" style="height: 12rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <template v-else>
      <div class="legend-row">
        <span class="legend-item is-static"><span class="legend-swatch" style="background:#2E2E38;height:2px" />History</span>
        <span
          v-for="name in scenarioNames" :key="name"
          class="legend-item"
          :class="{ 'is-off': isHidden(name) }"
          @click="toggleScenario(name)"
        >
          <span
            class="legend-swatch"
            :class="{ 'legend-dashed': scenarioStyle(name).dash }"
            :style="scenarioStyle(name).dash
              ? { borderTopColor: scenarioStyle(name).color }
              : { background: scenarioStyle(name).color, height: (name === 'Baseline' ? '3px' : '2px') }"
          />
          {{ name }}
        </span>
      </div>

      <div
        v-if="!selectedTargets.length"
        class="panel flex flex-column align-items-center justify-content-center gap-2"
        style="height: 16rem"
      >
        <i class="pi pi-filter-slash text-3xl text-color-secondary opacity-50" />
        <div class="text-sm font-medium">
          {{ forecastTargets.length ? 'Select at least one target variable' : 'This analysis run has no forecast targets' }}
        </div>
      </div>
      <div v-else class="fin-grid" :class="{ 'fin-grid--single': singleTarget }">
        <div v-for="fin in cards" :key="fin.key" class="panel">
          <div class="fin-head">
            <div>
              <div class="fin-title">{{ fin.title }}</div>
              <div class="fin-unit">{{ fin.unit }}</div>
            </div>
          </div>

          <div v-if="fin.unavailable" class="fin-empty">
            No forecast data available for <span class="font-medium">{{ fin.title }}</span> on the active analysis run.
          </div>
          <apexchart
            v-else
            type="line"
            :height="singleTarget ? 340 : 260"
            :options="fin.options"
            :series="fin.series"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.field-col { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }

.legend-row { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-color-secondary); cursor: pointer; user-select: none; transition: opacity 0.15s ease; }
.legend-item.is-static { cursor: default; }
.legend-item.is-off { opacity: 0.4; text-decoration: line-through; }
.legend-swatch { width: 16px; height: 2px; display: inline-block; }
.legend-dashed { border-top: 2px dashed #9B9BA6; height: 0; background: transparent !important; }

.fin-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.fin-grid--single { grid-template-columns: 1fr; }
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 18px 20px;
}
.fin-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
.fin-title { font-size: 13.5px; font-weight: 700; }
.fin-unit { font-size: 11.5px; color: var(--text-color-muted); margin-top: 2px; }
.fin-empty { font-size: 12.5px; color: var(--text-color-muted); padding: 2rem 0; }
</style>
