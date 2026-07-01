<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'

import calibrationsAPI from '@/api/calibrationsAPI'
import datasetsAPI from '@/api/datasetsAPI'
import forecastRunsAPI from '@/api/forecastRunsAPI'

const router = useRouter()
const toast  = useToast()

const calRuns     = ref([])
const datasets    = ref([])
const loadingInit = ref(false)

const calRunOptions = computed(() =>
  calRuns.value.map(r => ({
    label: `${r.target_col ?? '—'}  ·  ${r.config_name ?? '—'}  ·  ${r.run_id.slice(0, 8)}…`,
    value: r.run_id,
  }))
)

const datasetOptions = computed(() =>
  datasets.value.map(d => ({
    label: `${d.name}  ·  ${d.row_count?.toLocaleString() ?? '?'} rows`,
    value: d.id,
  }))
)

const selectedCalRunId   = ref(null)
const selectedDatasetId  = ref(null)
const selectedSegmentKey = ref(null)
const runName            = ref('')
const submitting         = ref(false)

// Segments for the selected calibration run (only when segmented)
const segments        = ref([])
const loadingSegments = ref(false)

const selectedCalRun = computed(() =>
  calRuns.value.find(r => r.run_id === selectedCalRunId.value) ?? null
)

const isSegmented = computed(() => !!selectedCalRun.value?.seg_sectors_json)

const segmentOptions = computed(() =>
  segments.value
    .filter(s => s.status === 'success')
    .map(s => ({
      label: `${s.sector}  ·  ${s.split_by}: ${s.split_value}`,
      value: s.segment_key,
    }))
)

watch(selectedCalRunId, async (runId) => {
  selectedSegmentKey.value = null
  segments.value = []
  if (!runId || !isSegmented.value) return
  loadingSegments.value = true
  try {
    const { data } = await calibrationsAPI.segments(runId)
    segments.value = data?.segments ?? []
  } catch {
    // non-fatal — segment picker stays empty
  } finally {
    loadingSegments.value = false
  }
})

const canLaunch = computed(() => selectedCalRunId.value != null && selectedDatasetId.value != null)

const launch = async () => {
  if (!canLaunch.value) return
  submitting.value = true
  try {
    await forecastRunsAPI.create({
      calibration_run_id: selectedCalRunId.value,
      dataset_id:         selectedDatasetId.value,
      name:               runName.value.trim() || null,
      segment_key:        selectedSegmentKey.value || undefined,
    })
    toast.add({ severity: 'success', summary: 'Forecast run queued', life: 3000 })
    router.push({ name: 'forecast_jobs' })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Launch failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  loadingInit.value = true
  try {
    const [crResp, dsResp] = await Promise.all([
      calibrationsAPI.list({ status: 'success', per_page: 200 }),
      datasetsAPI.listByKind('forecast'),
    ])
    calRuns.value  = (crResp.data?.items ?? crResp.data) ?? []
    datasets.value = (dsResp.data ?? []).filter(d => d.file_path)
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loadingInit.value = false
  }
})
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 1040px">
    <!-- Header -->
    <header class="flex align-items-end justify-content-between mb-5 flex-wrap gap-3">
      <div>
        <div class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">Forecast</div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">New Forecast Run</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">
          Apply a calibrated model to a forward-looking dataset to generate per-client predictions.
        </p>
      </div>
      <Button
        v-can="'forecast:execute'"
        label="Launch"
        icon="pi pi-play"
        :loading="submitting"
        :disabled="!canLaunch || loadingInit || submitting"
        @click="launch"
      />
    </header>

    <!-- Card: Calibration model -->
    <div class="form-card mb-4">
      <div class="form-card-head">
        <div class="text-xs text-color-secondary uppercase font-semibold" style="letter-spacing: 0.06em">
          Calibration Model
        </div>
      </div>

      <div class="form-row">
        <div class="form-label">
          <div class="font-medium text-sm">Model</div>
          <div class="text-xs text-color-secondary mt-1">
            Select a successful calibration run whose trained model will be applied to the forecast dataset.
          </div>
        </div>
        <div class="form-input">
          <Dropdown
            v-model="selectedCalRunId"
            :options="calRunOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="Select calibration run"
            :loading="loadingInit"
            :disabled="loadingInit"
            class="w-full"
            filter
          />
          <div v-if="!loadingInit && calRuns.length === 0" class="text-xs text-color-secondary mt-1">
            No successful calibration runs found. Run a calibration first.
          </div>
          <div v-if="selectedCalRun" class="mt-2 p-2 surface-ground border-round text-xs">
            <span class="text-color-secondary">Target variable: </span>
            <span class="font-mono font-semibold">{{ selectedCalRun.target_col ?? '—' }}</span>
            <span class="text-color-secondary ml-3">Features: </span>
            <span class="font-mono">{{ selectedCalRun.feature_cols ?? 'auto-detected' }}</span>
          </div>
        </div>
      </div>

      <!-- Segment picker: only shown for segmented calibration runs -->
      <div v-if="isSegmented" class="form-row" style="border-bottom: 0">
        <div class="form-label">
          <div class="font-medium text-sm">Segment <span class="text-color-secondary font-normal">(optional)</span></div>
          <div class="text-xs text-color-secondary mt-1">
            Target a single segment's model. Leave blank to run all segments and route each client automatically.
          </div>
        </div>
        <div class="form-input">
          <Dropdown
            v-model="selectedSegmentKey"
            :options="segmentOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="All segments (default)"
            :loading="loadingSegments"
            :disabled="loadingSegments || segmentOptions.length === 0"
            class="w-full"
            showClear
            filter
          />
          <div v-if="!loadingSegments && segmentOptions.length === 0" class="text-xs text-color-secondary mt-1">
            No successful segments found for this calibration run.
          </div>
        </div>
      </div>
    </div>

    <!-- Card: Forecast dataset -->
    <div class="form-card mb-4">
      <div class="form-card-head">
        <div class="text-xs text-color-secondary uppercase font-semibold" style="letter-spacing: 0.06em">
          Forecast Dataset
        </div>
      </div>

      <div class="form-row" style="border-bottom: 0">
        <div class="form-label">
          <div class="font-medium text-sm">Dataset</div>
          <div class="text-xs text-color-secondary mt-1">
            Must contain the same feature columns used during calibration.
            Include <span class="font-mono">client_id</span> and <span class="font-mono">date</span> columns
            so predictions can be matched to clients and years in the credit risk analysis.
          </div>
        </div>
        <div class="form-input">
          <Dropdown
            v-model="selectedDatasetId"
            :options="datasetOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="Select forecast dataset"
            :loading="loadingInit"
            :disabled="loadingInit"
            class="w-full"
            filter
          />
          <div v-if="!loadingInit && datasets.length === 0" class="text-xs text-color-secondary mt-1">
            No forecast datasets found. Go to
            <a class="text-primary cursor-pointer" @click="router.push({ name: 'datasets' })">Datasets</a>
            and upload a file with type "Forecast".
          </div>
        </div>
      </div>
    </div>

    <!-- Card: Optional name -->
    <div class="form-card mb-5">
      <div class="form-card-head">
        <div class="text-xs text-color-secondary uppercase font-semibold" style="letter-spacing: 0.06em">
          Optional
        </div>
      </div>

      <div class="form-row" style="border-bottom: 0">
        <div class="form-label">
          <div class="font-medium text-sm">Run Name</div>
          <div class="text-xs text-color-secondary mt-1">A short label to identify this forecast run.</div>
        </div>
        <div class="form-input">
          <InputText
            v-model="runName"
            placeholder="e.g. Q1 2025 Baseline Forecast"
            class="w-full"
          />
        </div>
      </div>
    </div>

    <div class="flex gap-2">
      <Button v-can="'forecast:execute'" label="Launch" icon="pi pi-play" :loading="submitting" :disabled="!canLaunch || loadingInit || submitting" @click="launch" />
      <Button label="Cancel" severity="secondary" text @click="router.push({ name: 'forecast_jobs' })" />
    </div>

  </div>
</template>

<style scoped>
.form-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(20, 20, 40, 0.06), 0 1px 2px rgba(20, 20, 40, 0.04);
}

.form-card-head {
  padding: 0.85rem 1.5rem;
  border-bottom: 1px solid var(--surface-border);
  background: var(--surface-section);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1.6fr;
  gap: 1.5rem;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--surface-border);
  align-items: start;
}

.form-label { padding-top: 0.2rem; }
.form-input { display: flex; flex-direction: column; gap: 0.25rem; }
</style>
