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

const companyOptions = computed(() => (companiesBySector.value[selectedSector.value] || []))

const forecastData = ref(null) // { sector, client_id, metrics: [...] }

async function fetchMeta() {
  loading.value = true
  try {
    const { data } = await creditRiskAPI.analysisMeta()
    sectors.value = data.sectors ?? []
    companiesBySector.value = data.companies_by_sector ?? {}
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
  loading.value = true
  errorMessage.value = null
  try {
    const { data } = await creditRiskAPI.analysisForecast({
      sector: selectedSector.value,
      client_id: selectedCompany.value || undefined,
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

onMounted(async () => {
  await fetchMeta()
  if (selectedSector.value) await fetchForecast()
})

// ── SVG chart geometry — mirrors the design prototype's segPath/tick formulas ──
const PLOT_X0 = 42, PLOT_W = 446, PLOT_TOP = 10, PLOT_BOTTOM = 186, PLOT_H = 162
const SPLIT_FRAC = 0.55

function segPath(points, lo, hi, x0, x1) {
  return points.map((p, i) => {
    const frac = points.length > 1 ? i / (points.length - 1) : 0
    const x = PLOT_X0 + (x0 + frac * (x1 - x0)) * PLOT_W
    const y = PLOT_BOTTOM - ((p.value - lo) / (hi - lo || 1)) * PLOT_H
    return (i ? 'L' : 'M') + x.toFixed(1) + ',' + y.toFixed(1)
  }).join(' ')
}

const SCENARIO_STYLE = {
  Baseline: { color: '#E8C400', width: 2.6, dash: null },
  Adverse: { color: '#9B9BA6', width: 1.6, dash: null },
  'Severely Adverse': { color: '#9B9BA6', width: 1.6, dash: '5 4' },
}

function buildCard(metric) {
  if (!metric.available) return { ...metric, unavailable: true }

  const hist = metric.history || []
  const scenarioEntries = Object.entries(metric.scenarios || {})
  const allVals = [
    ...hist.map(p => p.value),
    ...scenarioEntries.flatMap(([, pts]) => pts.map(p => p.value)),
  ]
  if (!allVals.length) return { ...metric, unavailable: true }

  const lo = Math.min(...allVals), hi = Math.max(...allVals)
  const pad = (hi - lo) * 0.12 || 1
  const l2 = lo - pad, h2 = hi + pad

  const ticks = [0.15, 0.5, 0.85].map(t => ({
    y: +(PLOT_BOTTOM - t * PLOT_H + 3).toFixed(1),
    label: (l2 + (h2 - l2) * t).toFixed(0),
  }))

  const histD = hist.length ? segPath(hist, l2, h2, 0, SPLIT_FRAC) : null
  const scenarioPaths = scenarioEntries.map(([name, pts]) => {
    const style = SCENARIO_STYLE[name] ?? { color: '#2D6FD6', width: 1.6, dash: null }
    return { name, style, d: segPath(pts, l2, h2, SPLIT_FRAC, 1) }
  })
  // Baseline drawn last (on top), matching design's path order
  scenarioPaths.sort((a, b) => (a.name === 'Baseline' ? 1 : b.name === 'Baseline' ? -1 : 0))

  const baseline = metric.scenarios?.Baseline || []
  const splitX = (PLOT_X0 + SPLIT_FRAC * PLOT_W).toFixed(1)

  const xLabels = []
  if (hist.length) xLabels.push({ x: PLOT_X0, label: hist[0].year })
  if (hist.length) xLabels.push({ x: +splitX, label: hist[hist.length - 1].year })
  if (baseline.length > 2) {
    const mid = baseline[Math.floor((baseline.length - 1) / 2)]
    const frac = SPLIT_FRAC + ((baseline.length - 1) / 2 / (baseline.length - 1)) * (1 - SPLIT_FRAC)
    xLabels.push({ x: (PLOT_X0 + frac * PLOT_W).toFixed(1), label: mid.year })
  }
  if (baseline.length) xLabels.push({ x: PLOT_X0 + PLOT_W, label: baseline[baseline.length - 1].year })

  return {
    ...metric,
    unavailable: false,
    ticks,
    histD,
    scenarioPaths,
    splitX,
    xLabels,
  }
}

const cards = computed(() => (forecastData.value?.metrics || []).map(buildCard))
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
        <span class="legend-item"><span class="legend-swatch" style="background:#2E2E38;height:2px" />History</span>
        <span class="legend-item"><span class="legend-swatch" style="background:#E8C400;height:3px" />Baseline</span>
        <span class="legend-item"><span class="legend-swatch" style="background:#9B9BA6;height:2px" />Adverse</span>
        <span class="legend-item"><span class="legend-swatch legend-dashed" />Severely Adverse</span>
      </div>

      <div class="fin-grid">
        <div v-for="fin in cards" :key="fin.key" class="panel">
          <div class="fin-head">
            <div>
              <div class="fin-title">{{ fin.title }}</div>
              <div class="fin-unit">{{ fin.unit }}</div>
            </div>
            <div class="flex-1" />
            <div v-if="!fin.unavailable" class="text-right">
              <div class="font-mono fin-val">{{ fin.value }}</div>
              <div class="font-mono fin-delta">{{ fin.delta_pct >= 0 ? '+' : '' }}{{ fin.delta_pct }}{{ fin.key === 'cogs_to_revenue' ? 'pp' : '%' }} vs {{ fin.base_year }} · baseline latest</div>
            </div>
          </div>

          <div v-if="fin.unavailable" class="fin-empty">
            Requires a forecast run linked for <span class="font-mono">{{ fin.key === 'cogs_to_revenue' ? 'total_revenue &amp; total_cogs' : fin.slot }}</span> on the active analysis run.
          </div>
          <svg v-else viewBox="0 0 500 210" class="fin-svg">
            <template v-for="t in fin.ticks" :key="t.y">
              <line x1="42" :y1="t.y" x2="492" :y2="t.y" stroke="#F0F0F3" stroke-width="1" />
              <text x="34" :y="t.y" text-anchor="end" font-family="IBM Plex Mono" font-size="9" fill="#9B9BA6">{{ t.label }}</text>
            </template>
            <line :x1="fin.splitX" y1="10" :x2="fin.splitX" y2="192" stroke="#D8D8DE" stroke-width="1" stroke-dasharray="4 3" />
            <text :x="+fin.splitX + 5" y="20" font-family="IBM Plex Mono" font-size="9" fill="#9B9BA6">FORECAST &rarr;</text>
            <path v-if="fin.histD" :d="fin.histD" fill="none" stroke="#2E2E38" stroke-width="1.8" />
            <path
              v-for="sp in fin.scenarioPaths" :key="sp.name"
              :d="sp.d" fill="none" :stroke="sp.style.color" :stroke-width="sp.style.width"
              :stroke-dasharray="sp.style.dash"
            />
            <text
              v-for="xl in fin.xLabels" :key="xl.label"
              :x="xl.x" y="206" text-anchor="middle" font-family="IBM Plex Mono" font-size="9" fill="#9B9BA6"
            >{{ xl.label }}</text>
          </svg>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.field-col { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }

.legend-row { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-color-secondary); }
.legend-swatch { width: 16px; height: 2px; display: inline-block; }
.legend-dashed { border-top: 2px dashed #9B9BA6; height: 0; }

.fin-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 18px 20px;
}
.fin-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
.fin-title { font-size: 13.5px; font-weight: 700; }
.fin-unit { font-size: 11.5px; color: var(--text-color-muted); margin-top: 2px; }
.fin-val { font-size: 19px; font-weight: 600; }
.fin-delta { font-size: 11px; color: var(--text-color-muted); }
.fin-svg { width: 100%; height: auto; display: block; }
.fin-empty { font-size: 12.5px; color: var(--text-color-muted); padding: 2rem 0; }
</style>
