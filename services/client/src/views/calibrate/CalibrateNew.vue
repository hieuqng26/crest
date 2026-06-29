<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import { datasets, getDataset, fetchDatasets } from '@/views/ingest/datasetsStore'
import { configs, registry, fetchConfigs } from '@/views/configure/configsStore'
import segmentationConfigsAPI from '@/api/segmentationConfigsAPI'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const selectedDatasetId = ref(null)
const selectedConfig = ref(route.query.config_id ? Number(route.query.config_id) : null)
const selectedSegConfigId = ref(null)
const submitting = ref(false)

const segmentationConfigs = ref([])

const selectedConfigMeta = computed(() =>
  configs.value.find(c => c.id === selectedConfig.value) || null
)
const algorithmMeta = computed(() =>
  selectedConfigMeta.value
    ? registry.value.find(a => a.algorithm === selectedConfigMeta.value.algorithm) || null
    : null
)
const selectedDataset = computed(() => getDataset(selectedDatasetId.value) || null)
const selectedSegConfig = computed(() =>
  segmentationConfigs.value.find(c => c.id === selectedSegConfigId.value) || null
)

const datasetOptions = computed(() =>
  datasets.value.map(d => ({
    label: `${d.name} (${d.row_count.toLocaleString()} rows · ${d.columns.length} cols)`,
    value: d.id,
  }))
)

const configOptions = computed(() =>
  configs.value.map(c => ({ label: `${c.name} — ${c.algorithm}`, value: c.id }))
)

const segConfigOptions = computed(() => [
  { label: 'None — train a single model', value: null },
  ...segmentationConfigs.value.map(c => ({ label: c.name, value: c.id })),
])

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
    const { data } = await calibrationsAPI.create({
      dataset_id:             selectedDatasetId.value,
      model_config_id:        selectedConfig.value,
      segmentation_config_id: selectedSegConfigId.value || null,
      target_col:             targetCol.value,
      feature_cols:           featureCols.value,
    })
    toast.add({ severity: 'success', summary: 'Queued', detail: `Run ${data.run_id}`, life: 3000 })
    router.push({ name: 'calibrate_run', params: { run_id: data.run_id }, query: { tab: 'progress' } })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Launch failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  const [, , { data }] = await Promise.all([
    fetchDatasets(),
    fetchConfigs(),
    segmentationConfigsAPI.list(),
  ])
  segmentationConfigs.value = data
})
</script>

<template>
  <div class="p-4">
    <h2 class="text-2xl font-semibold mb-4">New Calibration Run</h2>

    <!-- Dataset -->
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

    <!-- Segmentation (optional) -->
    <div class="surface-card border-round shadow-1 p-4 mb-4">
      <h3 class="text-base font-semibold m-0 mb-1">Segmentation <span class="text-color-secondary font-normal">(Optional)</span></h3>
      <p class="text-xs text-color-secondary m-0 mb-3">
        Train a separate model per portfolio segment (sector × subsector / country).
        <router-link :to="{ name: 'segmentation_configs' }" class="text-primary ml-1">Manage configs →</router-link>
      </p>
      <Dropdown
        v-model="selectedSegConfigId"
        :options="segConfigOptions"
        optionLabel="label"
        optionValue="value"
        class="w-full"
      />
      <div v-if="selectedSegConfig" class="surface-ground border-round p-3 mt-2 flex flex-wrap gap-3">
        <div class="flex flex-column">
          <span class="text-xs text-color-secondary uppercase">Default split</span>
          <span class="font-mono text-sm">{{ selectedSegConfig.default_split }}</span>
        </div>
        <div class="flex flex-column">
          <span class="text-xs text-color-secondary uppercase">Max segments</span>
          <span class="font-mono text-sm">{{ selectedSegConfig.max_segments }}</span>
        </div>
        <div v-if="selectedSegConfig.sector_rules?.length" class="w-full">
          <span class="text-xs text-color-secondary uppercase block mb-1">Sector overrides</span>
          <div class="flex flex-wrap gap-2">
            <Tag
              v-for="r in selectedSegConfig.sector_rules"
              :key="r.sector"
              :value="`${r.sector}: ${r.split_by} (top ${r.max_segments ?? selectedSegConfig.max_segments})`"
              severity="secondary"
              class="text-xs"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Model configuration -->
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

    <!-- Variables -->
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
