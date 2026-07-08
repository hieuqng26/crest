<script setup>
import { ref, computed, watch } from 'vue'
import forecastRunsAPI from '@/api/forecastRunsAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import LogsPanel from './LogsPanel.vue'
import { probeColumns } from './resultColumns.js'

const props = defineProps({
  targets: { type: Array, required: true } // [{ target_col, calibration, forecast }]
})

const targetsWithForecast = computed(() => props.targets.filter((t) => t.forecast))
const selectedTargetCol = ref(targetsWithForecast.value[0]?.target_col ?? null)
const selectedTarget = computed(() => targetsWithForecast.value.find((t) => t.target_col === selectedTargetCol.value) ?? null)
const selectedForecast = computed(() => selectedTarget.value?.forecast ?? null)

// A segment re-run keeps this forecast run at "success" while its rows for that
// segment still come from the previous model; the count is the only stale signal.
const retrainingCount = computed(() => selectedTarget.value?.calibration?.retraining_segment_count ?? 0)

const columns = ref([])
const fetchPage = (params) => forecastRunsAPI.results(selectedForecast.value.run_id, params)
const fetchDistinct = (column) => forecastRunsAPI.resultsDistinct(selectedForecast.value.run_id, column)

// Show live logs only while the selected forecast is still running.
const isForecastLive = computed(() => {
  const s = selectedForecast.value?.status
  return s === 'running' || s === 'queued'
})

// Key on stable primitives, not the forecast object: the 5s workflow poll
// replaces the whole target graph each tick, so watching the object itself
// re-probed columns (and remounted the table) on every poll for no reason.
// The run_id + finished_at pair only changes when results actually change.
const forecastKey = computed(() =>
  selectedForecast.value ? `${selectedForecast.value.run_id}:${selectedForecast.value.finished_at ?? ''}` : ''
)
watch(forecastKey, async (key) => {
  columns.value = []
  if (!key) return
  columns.value = await probeColumns(fetchPage)
}, { immediate: true })
</script>

<template>
  <div class="forecast-tab">
    <div v-if="targetsWithForecast.length === 0" class="panel empty-note">
      <i class="pi pi-clock" />
      <p>No forecast results yet — forecasts run automatically once training completes.</p>
    </div>

    <template v-else>
      <div class="filter-bar">
        <div class="filter-col">
          <label class="field-label">Target</label>
          <EySelect v-model="selectedTargetCol" :options="targetsWithForecast.map(t => ({ label: t.target_col, value: t.target_col }))" optionLabel="label" optionValue="value" class="font-mono" />
        </div>
      </div>

      <div v-if="retrainingCount > 0" class="retraining-banner">
        <i class="pi pi-sync" />
        <span>{{ retrainingCount }} segment{{ retrainingCount > 1 ? 's are' : ' is' }} re-training — forecast rows for {{ retrainingCount > 1 ? 'those segments' : 'that segment' }} still reflect the previous model and will refresh automatically.</span>
      </div>

      <div class="panel results-panel">
        <CommonDataTable
          v-if="columns.length"
          :key="`${selectedForecast.run_id}:${selectedForecast.finished_at ?? ''}`"
          :columns="columns"
          :fetch-page="fetchPage"
          :fetch-distinct="fetchDistinct"
          empty-message="No results yet."
        />
      </div>

      <LogsPanel
        v-if="isForecastLive"
        :key="`log-${selectedForecast.run_id}`"
        :kind="'forecast'"
        :run-id="selectedForecast.run_id"
        :status="selectedForecast.status"
        collapsible
      />
    </template>
  </div>
</template>

<style scoped>
.forecast-tab { display: flex; flex-direction: column; gap: 16px; }

.retraining-banner {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  font-size: 12.5px; color: var(--text-color-secondary);
  background: var(--surface-inset); border: 1px solid var(--surface-border);
  border-left: 3px solid var(--running-color); border-radius: 2px;
}
.retraining-banner i { color: var(--running-color); font-size: 13px; }

.filter-bar { display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; background: var(--surface-inset); border-radius: 2px; padding: 14px 16px; }
.filter-col { display: flex; flex-direction: column; gap: 6px; min-width: 200px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }

.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; }
.results-panel { overflow: hidden; }

.empty-note { text-align: center; color: var(--text-color-muted); padding: 32px 20px; }
.empty-note i { font-size: 22px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-note p { margin: 0; font-size: 13px; }
</style>
