<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import creditRiskAPI from '@/api/creditRiskAPI'
import { cssVar, scenarioStyle } from '@/utils/chartTheme'
import LinePlot from '@/components/charts/LinePlot.vue'
import PageHeader from '@/components/ui/PageHeader.vue'

const router = useRouter()

const loading      = ref(false)
const noActiveRun  = ref(false)
const errorMessage = ref(null)

// When a run's analysis series hasn't been materialised, the API returns 202
// {status:'materializing'} and kicks off a background job. We show a "preparing"
// state and retry on a bounded schedule until the data is ready.
const materializing = ref(false)
let materializeTimer = null
let materializeAttempts = 0
const MAX_MATERIALIZE_ATTEMPTS = 45 // ~3 min at 4s
const isMaterializing = (data) => data?.status === 'materializing'
function scheduleMaterializeRetry(fn) {
  if (materializeAttempts >= MAX_MATERIALIZE_ATTEMPTS) {
    materializing.value = false
    errorMessage.value = 'Preparing analysis data is taking longer than expected. Please refresh the page.'
    return
  }
  materializeAttempts += 1
  materializeTimer = setTimeout(fn, 4000)
}
onUnmounted(() => clearTimeout(materializeTimer))

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
    if (isMaterializing(data)) {
      materializing.value = true
      scheduleMaterializeRetry(fetchMeta)
      return
    }
    materializing.value = false
    materializeAttempts = 0
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
    if (isMaterializing(data)) {
      materializing.value = true
      scheduleMaterializeRetry(fetchForecast)
      return
    }
    materializing.value = false
    forecastData.value = data
  } catch (e) {
    forecastData.value = null
    errorMessage.value = e?.response?.data?.error ?? e.message
  } finally {
    loading.value = false
  }
}

// Coalesce the filter cascade: changing a sector also resets the company and can
// retrigger several watchers in one tick — debounce so we fire one request.
let forecastTimer = null
function scheduleForecast() {
  if (forecastTimer) clearTimeout(forecastTimer)
  forecastTimer = setTimeout(fetchForecast, 150)
}

watch(selectedSector, () => { selectedCompany.value = null; scheduleForecast() })
watch(selectedCompany, scheduleForecast)
watch(selectedTargets, scheduleForecast)

onMounted(async () => {
  await fetchMeta()
  // fetchMeta sets selectedSector, whose watcher already schedules the first
  // forecast fetch — no explicit call here (avoids a duplicate request).
})

// ── chart series ─────────────────────────────────────────────────────────────
// History occupies the ink slot; the three scenarios use the shared scenario
// styling so they render identically to every other chart in the app.
const historyColor = () => cssVar('--chart-2')
const showHistory = ref(false)

// Injected into each plot's kebab menu — toggles the History line on every card.
const historyMenuItems = computed(() => [{
  label: showHistory.value ? 'Hide history' : 'Show history',
  icon: showHistory.value ? 'pi pi-eye-slash' : 'pi pi-eye',
  command: () => { showHistory.value = !showHistory.value },
}])

function buildCard(metric) {
  if (!metric.available) return { ...metric, unavailable: true }

  const hist = metric.history || []
  const scenarioEntries = Object.entries(metric.scenarios || {})
  if (!hist.length && !scenarioEntries.length) return { ...metric, unavailable: true }

  const lastHist = hist.length ? hist[hist.length - 1] : null

  const series = []
  if (hist.length && showHistory.value) {
    series.push({
      name: 'History',
      x: hist.map((p) => p.year),
      y: hist.map((p) => p.value),
      color: historyColor(),
      width: 1.8,
    })
  }

  let fallbackIdx = 0
  for (const [name, pts] of scenarioEntries) {
    const st = scenarioStyle(name, fallbackIdx++)
    // Prepend history's last point so the forecast path joins continuously
    // (removes the visual "jump" at the history→forecast boundary).
    const x = (lastHist ? [lastHist.year] : []).concat(pts.map((p) => p.year))
    const y = (lastHist ? [lastHist.value] : []).concat(pts.map((p) => p.value))
    // Dots on the (yearly) scenario paths only — History is dense monthly data.
    series.push({ name, x, y, color: st.color, width: st.width, dash: st.dash, mode: 'lines+markers' })
  }

  return { ...metric, unavailable: false, series }
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

    <!-- Preparing analysis data (backend is materialising the series) -->
    <div v-else-if="materializing" class="panel flex flex-column align-items-center justify-content-center gap-3" style="height: 22rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
      <div class="text-center">
        <div class="text-sm font-medium mb-1">Preparing analysis data…</div>
        <div class="text-xs text-color-secondary">Computing this run's forecast series. This page will refresh automatically.</div>
      </div>
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="flex justify-content-center align-items-center" style="height: 12rem">
      <i class="pi pi-spin pi-spinner text-3xl text-color-secondary" />
    </div>

    <template v-else>
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
          <LinePlot
            v-else
            :series="fin.series"
            :height="singleTarget ? 340 : 260"
            y-tick-format=".2s"
            y-hover-format=".3s"
            x-tick-format="d"
            :extra-menu-items="historyMenuItems"
            :png-filename="`forecast-${fin.key}`"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.field-col { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }

/* Container-relative: 2-up on a normal desktop, collapses to one plot per row
 * when the grid gets narrow (≈ below 975px), independent of the sidebar state. */
.fin-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; }
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
