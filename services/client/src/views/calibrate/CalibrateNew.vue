<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import { datasets, getDataset, fetchDatasets } from '@/views/ingest/datasetsStore'
import { configs, registry, fetchConfigs } from '@/views/configure/configsStore'
import { intersectColumns, findUnjoinable, projectSchema } from './mergePlan'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const MAX_DATASETS = 3
const MERGE_TYPES = [
  { label: '⋈ Inner join', value: 'inner' },
  { label: '⟕ Left join',  value: 'left' },
  { label: '⟗ Outer join', value: 'outer' },
  { label: '∪ Union',      value: 'union' }
]

const selectedDatasetIds = ref([])
const mergeSteps = ref([])
const expandedDatasets = ref(new Set())
const toggleExpand = (id) => {
  const s = new Set(expandedDatasets.value)
  s.has(id) ? s.delete(id) : s.add(id)
  expandedDatasets.value = s
}
const selectedConfig = ref(route.query.config_id ? Number(route.query.config_id) : null)
const submitting = ref(false)

const selectedConfigMeta = computed(() =>
  configs.value.find(c => c.id === selectedConfig.value) || null
)
const algorithmMeta = computed(() =>
  selectedConfigMeta.value
    ? registry.value.find(a => a.algorithm === selectedConfigMeta.value.algorithm) || null
    : null
)

const datasetOptions = computed(() =>
  datasets.value.map(d => ({
    label: `${d.name} (${d.row_count.toLocaleString()} rows · ${d.columns.length} cols)`,
    value: d.id,
    disabled: selectedDatasetIds.value.includes(d.id)
  }))
)

const configOptions = computed(() =>
  configs.value.map(c => ({ label: `${c.name} — ${c.algorithm}`, value: c.id }))
)

const selectedDatasets = computed(() =>
  selectedDatasetIds.value.map(getDataset).filter(Boolean)
)

const reconcileSteps = () => {
  const needed = Math.max(0, selectedDatasets.value.length - 1)
  if (mergeSteps.value.length > needed) {
    mergeSteps.value = mergeSteps.value.slice(0, needed)
  }
  while (mergeSteps.value.length < needed) {
    const i = mergeSteps.value.length
    const overlap = intersectColumns(
      selectedDatasets.value[i].columns,
      selectedDatasets.value[i + 1].columns
    )
    mergeSteps.value.push({ type: 'inner', on: overlap.slice(0, 1) })
  }
  // Refresh `on` whenever neighbours change
  for (let i = 0; i < mergeSteps.value.length; i++) {
    const overlap = intersectColumns(
      selectedDatasets.value[i].columns,
      selectedDatasets.value[i + 1].columns
    )
    const step = mergeSteps.value[i]
    step.on = (step.on || []).filter(c => overlap.includes(c))
    if (step.type !== 'union' && step.on.length === 0 && overlap.length > 0) {
      step.on = overlap.slice(0, 1)
    }
  }
}

watch(selectedDatasetIds, reconcileSteps, { deep: true })

const intersectionAt = (i) => intersectColumns(
  selectedDatasets.value[i]?.columns,
  selectedDatasets.value[i + 1]?.columns
)

const unjoinable = computed(() => findUnjoinable(selectedDatasets.value, mergeSteps.value))
const schema = computed(() => projectSchema(selectedDatasets.value, mergeSteps.value))

const targetCol = ref(null)
const featureCols = ref([])

const columnOptions = computed(() => schema.value.columns ?? [])
const featureOptions = computed(() =>
  columnOptions.value.filter(c => c !== targetCol.value)
)

watch(schema, () => {
  targetCol.value = null
  featureCols.value = []
})

const canLaunch = computed(() =>
  selectedDatasetIds.value.length >= 1 &&
  selectedConfig.value &&
  unjoinable.value.length === 0 &&
  !!targetCol.value
)

const addDataset = (id) => {
  if (selectedDatasetIds.value.length >= MAX_DATASETS) return
  if (selectedDatasetIds.value.includes(id)) return
  selectedDatasetIds.value = [...selectedDatasetIds.value, id]
  pickerOpen.value = false
  pickerValue.value = null
}

const removeDataset = (idx) => {
  selectedDatasetIds.value = selectedDatasetIds.value.filter((_, i) => i !== idx)
}

const pickerOpen = ref(false)
const pickerValue = ref(null)
watch(pickerValue, (v) => { if (v != null) addDataset(v) })

const launch = async () => {
  if (!canLaunch.value) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Fix merge issues and pick a model config', life: 3000 })
    return
  }
  submitting.value = true
  try {
    const { data } = await calibrationsAPI.create({
      dataset_ids:     selectedDatasetIds.value,
      model_config_id: selectedConfig.value,
      merge_steps:     mergeSteps.value,
      target_col:      targetCol.value,
      feature_cols:    featureCols.value,
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
  await Promise.all([fetchDatasets(), fetchConfigs()])
})
</script>

<template>
  <div class="p-4">
    <h2 class="text-2xl font-semibold mb-4">New Calibration Run</h2>

    <!-- Datasets pipeline -->
    <div class="surface-card border-round shadow-1 p-4 mb-4">
      <div class="flex align-items-center justify-content-between mb-3">
        <div>
          <h3 class="text-base font-semibold m-0">Datasets</h3>
          <p class="text-xs text-color-secondary m-0 mt-1">Choose 1–3 datasets; configure how they merge.</p>
        </div>
        <div v-if="selectedDatasetIds.length < MAX_DATASETS">
          <Dropdown
            v-model="pickerValue"
            :options="datasetOptions"
            optionLabel="label"
            optionValue="value"
            optionDisabled="disabled"
            placeholder="+ Add dataset"
            class="w-20rem"
          />
        </div>
        <div v-else>
          <Tag value="Max 3 datasets" severity="secondary" />
        </div>
      </div>

      <!-- Empty state -->
      <div v-if="selectedDatasets.length === 0" class="surface-ground border-round p-4 text-center">
        <i class="pi pi-database text-3xl text-color-secondary block mb-2" />
        <p class="m-0 text-sm text-color-secondary">Pick a dataset to start.</p>
      </div>

      <!-- Pipeline -->
      <div v-else class="flex align-items-stretch gap-2 overflow-x-auto pb-2">
        <template v-for="(d, idx) in selectedDatasets" :key="d.id">
          <!-- Dataset card -->
          <div class="surface-ground border-round p-3 flex-shrink-0" style="min-width: 14rem; max-width: 16rem">
            <div class="flex align-items-start justify-content-between gap-2 mb-2">
              <span class="font-semibold text-sm" style="word-break: break-word">{{ d.name }}</span>
              <Button
                icon="pi pi-times"
                text rounded size="small"
                v-tooltip.top="'Remove'"
                @click="removeDataset(idx)"
              />
            </div>
            <div class="text-xs text-color-secondary">
              {{ d.row_count.toLocaleString() }} rows · {{ d.columns.length }} cols
            </div>
            <div class="flex flex-wrap gap-1 mt-2" :style="expandedDatasets.has(d.id) ? '' : 'max-height: 4.5rem; overflow: hidden'">
              <Chip
                v-for="c in d.columns"
                :key="c"
                :label="c"
                class="text-xs"
                style="font-size: 10px; padding: 2px 6px"
              />
            </div>
            <button
              v-if="d.columns.length > 4"
              class="mt-1 text-xs text-primary border-none bg-transparent cursor-pointer p-0"
              @click.stop="toggleExpand(d.id)"
            >
              {{ expandedDatasets.has(d.id) ? 'Show less' : `+${d.columns.length - 4} more` }}
            </button>
          </div>

          <!-- Merge step card (between datasets) -->
          <div
            v-if="idx < selectedDatasets.length - 1"
            class="border-round p-3 flex-shrink-0 flex flex-column gap-2 align-self-center"
            :class="unjoinable.includes(idx) ? 'border-1 border-red-500' : 'surface-card border-1 surface-border'"
            style="min-width: 14rem; max-width: 16rem"
          >
            <div class="flex align-items-center gap-2 mb-1">
              <i class="pi pi-arrow-right-arrow-left text-primary" />
              <span class="text-xs font-semibold uppercase text-color-secondary">Merge step {{ idx + 1 }}</span>
            </div>
            <Dropdown
              v-model="mergeSteps[idx].type"
              :options="MERGE_TYPES"
              optionLabel="label"
              optionValue="value"
              class="w-full"
            />
            <template v-if="mergeSteps[idx].type !== 'union'">
              <MultiSelect
                v-model="mergeSteps[idx].on"
                :options="intersectionAt(idx)"
                placeholder="Join key(s)"
                display="chip"
                class="w-full"
                :class="{ 'p-invalid': unjoinable.includes(idx) }"
              />
              <span v-if="intersectionAt(idx).length === 0" class="text-xs text-red-500">
                No shared columns
              </span>
              <span v-else class="text-xs text-color-secondary">
                {{ intersectionAt(idx).length }} shared column{{ intersectionAt(idx).length === 1 ? '' : 's' }}
              </span>
            </template>
            <span v-else class="text-xs text-color-secondary">
              Concat rows; keeps columns present in both.
            </span>
          </div>
        </template>
      </div>

      <Message
        v-if="unjoinable.length > 0"
        severity="error"
        :closable="false"
        class="mt-3"
      >
        <span v-for="i in unjoinable" :key="i">
          No valid join between
          <b>{{ selectedDatasets[i]?.name }}</b> and
          <b>{{ selectedDatasets[i + 1]?.name }}</b>{{ intersectionAt(i).length === 0 ? ' — no overlapping columns' : ' — pick a join key' }}.
        </span>
        Pick another dataset, change the merge order, or switch to a union.
      </Message>
    </div>

    <!-- Model configuration -->
    <div class="surface-card border-round shadow-1 mb-4 overflow-hidden">
      <!-- Header -->
      <div class="p-4 border-bottom-1 surface-border">
        <h3 class="text-base font-semibold m-0">Model Configuration</h3>
        <p class="text-xs text-color-secondary m-0 mt-1">Pick a saved model config. Training settings (split, scaler, hyperparameter search) are configured in the config itself.</p>
      </div>

      <!-- Configuration picker -->
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
