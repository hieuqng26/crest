<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import datasetsAPI from '@/api/datasetsAPI'
import { datasets, getDataset, fetchDatasets } from '@/views/ingest/datasetsStore'
import { configs, registry, fetchConfigs } from '@/views/configure/configsStore'

const route = useRoute()
const router = useRouter()
const toast = useToast()

// Dataset
const selectedDatasetId = ref(null)
const selectedDataset = computed(() => getDataset(selectedDatasetId.value) || null)
const datasetOptions = computed(() =>
  datasets.value
    .filter(d => d.kind === 'calibration')
    .map(d => ({
      label: `${d.name} (${d.row_count.toLocaleString()} rows · ${d.columns.length} cols)`,
      value: d.id,
    }))
)

// Sectors
const availableSectors = ref([])
const selectedSector = ref(null)
const loadingSectors = ref(false)

watch(selectedDatasetId, async (id) => {
  availableSectors.value = []
  selectedSector.value = null
  splitBy.value = 'subsector'
  maxSegments.value = 5
  if (!id) return
  loadingSectors.value = true
  try {
    const { data } = await datasetsAPI.sectors(id)
    availableSectors.value = data.sectors || []
  } catch {
    availableSectors.value = []
  } finally {
    loadingSectors.value = false
  }
})

watch(selectedSector, (v) => {
  if (!v) {
    splitBy.value = 'subsector'
    maxSegments.value = 5
  }
})

// Segmentation settings
const splitBy = ref('subsector')
const maxSegments = ref(5)

// Model config
const selectedConfig = ref(route.query.config_id ? Number(route.query.config_id) : null)
const configOptions = computed(() =>
  configs.value.map(c => ({ label: `${c.name} — ${c.algorithm}`, value: c.id }))
)
const selectedConfigMeta = computed(() =>
  configs.value.find(c => c.id === selectedConfig.value) || null
)
const algorithmMeta = computed(() =>
  selectedConfigMeta.value
    ? registry.value.find(a => a.algorithm === selectedConfigMeta.value.algorithm) || null
    : null
)

// Variables
const columnOptions = computed(() => selectedDataset.value?.columns ?? [])
const targetCol = ref(null)
const featureCols = ref([])
const featureOptions = computed(() =>
  columnOptions.value.filter(c => c !== targetCol.value)
)
watch(columnOptions, () => {
  targetCol.value = null
  featureCols.value = []
})

// Launch
const submitting = ref(false)
const canLaunch = computed(() =>
  !!selectedDatasetId.value &&
  !!selectedConfig.value &&
  !!targetCol.value
)

const launch = async () => {
  if (!canLaunch.value) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Select a dataset, model config, and target column', life: 3000 })
    return
  }
  submitting.value = true
  try {
    const payload = {
      dataset_id:     selectedDatasetId.value,
      model_config_id: selectedConfig.value,
      target_col:     targetCol.value,
      feature_cols:   featureCols.value,
      segmentation:   selectedSector.value
        ? { sectors: [selectedSector.value], split_by: splitBy.value, max_segments: maxSegments.value }
        : null,
    }
    const { data } = await calibrationsAPI.create(payload)
    toast.add({ severity: 'success', summary: 'Queued', detail: `Run ${data.run_id}`, life: 3000 })
    router.push({ name: 'calibrate_run', params: { run_id: data.run_id }, query: { tab: 'overview' } })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Launch failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    submitting.value = false
  }
}

onMounted(() => Promise.all([fetchDatasets(), fetchConfigs()]))
</script>

<template>
  <div class="p-4">
    <h2 class="text-2xl font-semibold mb-4">New Calibration Run</h2>

    <!-- 1. Dataset -->
    <div class="surface-card border-round shadow-1 p-4 mb-4">
      <h3 class="text-base font-semibold m-0 mb-1">Dataset</h3>
      <p class="text-xs text-color-secondary m-0 mb-3">Choose the dataset to calibrate on.</p>
      <Dropdown
        v-model="selectedDatasetId"
        :options="datasetOptions"
        optionLabel="label"
        optionValue="value"
        placeholder="Select dataset"
        class="w-full"
        filter
      />
      <div v-if="selectedDataset" class="surface-ground border-round p-3 mt-2 flex flex-wrap gap-3">
        <div class="flex flex-column">
          <span class="text-xs text-color-secondary uppercase">Rows</span>
          <span class="font-mono text-sm">{{ selectedDataset.row_count.toLocaleString() }}</span>
        </div>
        <div class="flex flex-column">
          <span class="text-xs text-color-secondary uppercase">Columns</span>
          <span class="font-mono text-sm">{{ selectedDataset.columns.length }}</span>
        </div>
      </div>
    </div>

    <!-- 2. Sectors (shown only when dataset has a sector column) -->
    <div v-if="selectedDatasetId && (availableSectors.length > 0 || loadingSectors)" class="surface-card border-round shadow-1 p-4 mb-4">
      <h3 class="text-base font-semibold m-0 mb-1">Sector</h3>
      <p class="text-xs text-color-secondary m-0 mb-3">
        Choose a sector to segment. Leave unset to train a single model on all data.
      </p>
      <div v-if="loadingSectors" class="flex align-items-center gap-2 text-color-secondary text-sm">
        <i class="pi pi-spin pi-spinner" /> Loading sectors…
      </div>
      <Dropdown
        v-else
        v-model="selectedSector"
        :options="availableSectors"
        placeholder="No segmentation — single model"
        showClear
        class="w-full"
      />
    </div>

    <!-- 3. Segmentation settings (shown only when a sector is selected) -->
    <div v-if="selectedSector !== null" class="surface-card border-round shadow-1 p-4 mb-4">
      <h3 class="text-base font-semibold m-0 mb-1">Segmentation</h3>
      <p class="text-xs text-color-secondary m-0 mb-3">
        Each selected sector will be split by the chosen dimension. The top N groups by EAD are trained individually; the rest are collapsed into "Others".
      </p>
      <div class="flex flex-column gap-4">
        <div class="flex flex-column gap-2">
          <label class="text-xs font-semibold uppercase text-color-secondary">Split By</label>
          <SelectButton
            v-model="splitBy"
            :options="[{ label: 'Subsector', value: 'subsector' }, { label: 'Country', value: 'country' }]"
            optionLabel="label"
            optionValue="value"
          />
        </div>
        <div class="flex flex-column gap-2" style="max-width: 14rem">
          <label class="text-xs font-semibold uppercase text-color-secondary">Max Segments per Sector</label>
          <InputNumber v-model="maxSegments" :min="2" :max="20" showButtons class="w-full" />
        </div>
      </div>
    </div>

    <!-- 4. Model configuration -->
    <div class="surface-card border-round shadow-1 mb-4 overflow-hidden">
      <div class="p-4 border-bottom-1 surface-border">
        <h3 class="text-base font-semibold m-0">Model Configuration</h3>
        <p class="text-xs text-color-secondary m-0 mt-1">Pick a saved model config. Training settings (split, scaler, hyperparameter search) are configured in the config itself.</p>
      </div>
      <section class="p-4 flex flex-column md:flex-row md:align-items-start gap-4">
        <div class="md:w-12rem flex-shrink-0">
          <div class="text-xs font-semibold uppercase text-color-secondary">Configuration</div>
          <div class="text-xs text-color-secondary mt-1">The algorithm and hyperparameters to calibrate.</div>
        </div>
        <div class="flex-1 flex flex-column gap-2">
          <Dropdown
            v-model="selectedConfig"
            :options="configOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="Select model configuration"
            class="w-full"
          />
          <div v-if="selectedConfigMeta" class="surface-ground border-round p-3 flex flex-wrap align-items-center gap-3">
            <div class="flex flex-column">
              <span class="text-xs text-color-secondary uppercase">Algorithm</span>
              <span class="font-mono text-sm">{{ selectedConfigMeta.algorithm }}</span>
            </div>
            <div class="flex flex-column">
              <span class="text-xs text-color-secondary uppercase">Split</span>
              <span class="font-mono text-sm">{{ Math.round((selectedConfigMeta.train_split ?? 0.8) * 100) }} / {{ 100 - Math.round((selectedConfigMeta.train_split ?? 0.8) * 100) }}</span>
            </div>
            <div v-if="selectedConfigMeta.scaler" class="flex flex-column">
              <span class="text-xs text-color-secondary uppercase">Scaler</span>
              <span class="font-mono text-sm">{{ selectedConfigMeta.scaler }}</span>
            </div>
            <Tag v-if="algorithmMeta" :value="algorithmMeta.family" severity="secondary" class="text-xs ml-auto" />
          </div>
          <span v-if="configOptions.length === 0" class="text-xs text-color-secondary">
            No configurations saved yet — create one in the Models module.
          </span>
        </div>
      </section>
    </div>

    <!-- 5. Variables -->
    <div class="surface-card border-round shadow-1 mb-4 overflow-hidden">
      <div class="p-4 border-bottom-1 surface-border">
        <h3 class="text-base font-semibold m-0">Variables</h3>
        <p class="text-xs text-color-secondary m-0 mt-1">Select the target to predict and which columns to use as features.</p>
      </div>
      <section class="p-4 flex flex-column gap-4">
        <div class="flex flex-column md:flex-row md:align-items-start gap-4">
          <div class="md:w-12rem flex-shrink-0">
            <div class="text-xs font-semibold uppercase text-color-secondary">Target Column</div>
            <div class="text-xs text-color-secondary mt-1">The variable to predict.</div>
          </div>
          <div class="flex-1">
            <Dropdown
              v-model="targetCol"
              :options="columnOptions"
              placeholder="Select target column"
              :disabled="columnOptions.length === 0"
              class="w-full"
              filter
            />
            <span v-if="columnOptions.length === 0" class="text-xs text-color-secondary mt-1 block">
              Select a dataset first.
            </span>
          </div>
        </div>
        <div class="flex flex-column md:flex-row md:align-items-start gap-4">
          <div class="md:w-12rem flex-shrink-0">
            <div class="text-xs font-semibold uppercase text-color-secondary">Feature Columns</div>
            <div class="text-xs text-color-secondary mt-1">Leave blank to use all non-target columns.</div>
          </div>
          <div class="flex-1">
            <MultiSelect
              v-model="featureCols"
              :options="featureOptions"
              placeholder="All non-target columns"
              :disabled="!targetCol || featureOptions.length === 0"
              display="chip"
              class="w-full"
              filter
            />
          </div>
        </div>
      </section>
    </div>

    <div class="flex gap-2">
      <Button v-can="'calibration:execute'" label="Launch" icon="pi pi-play" :loading="submitting" :disabled="!canLaunch || submitting" @click="launch" />
      <Button label="Cancel" severity="secondary" text @click="router.push({ name: 'calibrate_jobs' })" />
    </div>
  </div>
</template>
