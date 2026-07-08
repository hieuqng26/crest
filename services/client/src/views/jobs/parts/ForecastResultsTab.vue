<script setup>
import { ref, computed, watch } from 'vue'
import workflowsAPI from '@/api/workflowsAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import { probeColumns } from './resultColumns.js'

const props = defineProps({
  runId:   { type: String, required: true }, // workflow run_id
  targets: { type: Array, required: true }    // [{ target_col, calibration, forecast }]
})

const targetsWithForecast = computed(() => props.targets.filter((t) => t.forecast))

// Any target with a segment still re-training — its rows in the combined table
// reflect the previous model until the recompute lands.
const retrainingCount = computed(() =>
  props.targets.reduce((n, t) => n + (t.calibration?.retraining_segment_count ?? 0), 0)
)

const columns = ref([])
const fetchPage = (params) => workflowsAPI.forecastResults(props.runId, params)
const fetchDistinct = (column) => workflowsAPI.forecastResultsDistinct(props.runId, column)

// Re-probe columns (and remount the table) only when the set of completed
// forecasts actually changes — a stable string key, so the 5s workflow poll that
// replaces `targets` every tick doesn't churn this.
const completedKey = computed(() =>
  targetsWithForecast.value
    .filter((t) => t.forecast?.status === 'success')
    .map((t) => `${t.forecast.run_id}:${t.forecast.finished_at ?? ''}`)
    .join('|')
)

watch(completedKey, async (key) => {
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
      <div v-if="retrainingCount > 0" class="retraining-banner">
        <i class="pi pi-sync" />
        <span>{{ retrainingCount }} segment{{ retrainingCount > 1 ? 's are' : ' is' }} re-training — their forecast rows still reflect the previous model and will refresh automatically.</span>
      </div>

      <div class="panel results-panel">
        <CommonDataTable
          v-if="columns.length"
          :key="completedKey"
          :columns="columns"
          :fetch-page="fetchPage"
          :fetch-distinct="fetchDistinct"
          empty-message="No results yet."
        />
      </div>
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

.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; }
.results-panel { overflow: hidden; }

.empty-note { text-align: center; color: var(--text-color-muted); padding: 32px 20px; }
.empty-note i { font-size: 22px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-note p { margin: 0; font-size: 13px; }
</style>
