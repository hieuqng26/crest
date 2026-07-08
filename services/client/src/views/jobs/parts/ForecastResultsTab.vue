<script setup>
import { ref, computed, watch } from 'vue'
import forecastRunsAPI from '@/api/forecastRunsAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import RetrainingBanner from '@/components/ui/RetrainingBanner.vue'
import FilterBar from '@/components/ui/FilterBar.vue'
import FilterField from '@/components/ui/FilterField.vue'
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

watch(selectedForecast, async (fr) => {
  columns.value = []
  if (!fr) return
  columns.value = await probeColumns(fetchPage)
}, { immediate: true })
</script>

<template>
  <div class="forecast-tab">
    <div v-if="targetsWithForecast.length === 0" class="panel">
      <EmptyState icon="pi pi-clock">No forecast results yet — forecasts run automatically once training completes.</EmptyState>
    </div>

    <template v-else>
      <FilterBar>
        <FilterField label="Target">
          <EySelect v-model="selectedTargetCol" :options="targetsWithForecast.map(t => ({ label: t.target_col, value: t.target_col }))" optionLabel="label" optionValue="value" class="font-mono" />
        </FilterField>
      </FilterBar>

      <RetrainingBanner v-if="retrainingCount > 0">
        {{ retrainingCount }} segment{{ retrainingCount > 1 ? 's are' : ' is' }} re-training — forecast rows for {{ retrainingCount > 1 ? 'those segments' : 'that segment' }} still reflect the previous model and will refresh automatically.
      </RetrainingBanner>

      <div class="panel results-panel">
        <CommonDataTable
          v-if="columns.length"
          :key="`${selectedForecast.run_id}:${selectedForecast.finished_at ?? ''}`"
          card
          title="Forecast results"
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
.results-panel { overflow: hidden; }
</style>
