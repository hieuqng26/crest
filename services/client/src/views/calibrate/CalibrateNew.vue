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
const selectedConfig = ref(route.query.config_id ? Number(route.query.config_id) : null)
const trainSplit = ref(80)
const scaler = ref('none')
const cvSearch = ref({ mode: 'none', folds: 5, nIter: 20, scoring: 'roc_auc' })
const paramGrid = ref({})
const submitting = ref(false)

const SCALER_OPTIONS = [
  { label: 'None',           value: 'none' },
  { label: 'Standard',       value: 'standard' },
  { label: 'Min-Max',        value: 'minmax' },
  { label: 'Robust',         value: 'robust' }
]
const SEARCH_OPTIONS = [
  { label: 'None',         value: 'none' },
  { label: 'Grid',         value: 'grid' },
  { label: 'Randomized',   value: 'random' }
]
const SCORING_OPTIONS = [
  { label: 'ROC AUC',  value: 'roc_auc' },
  { label: 'Accuracy', value: 'accuracy' },
  { label: 'F1',       value: 'f1' },
  { label: 'Precision', value: 'precision' },
  { label: 'Recall',   value: 'recall' },
  { label: 'Neg. log loss', value: 'neg_log_loss' },
  { label: 'RMSE',     value: 'neg_root_mean_squared_error' }
]
const NUMERIC_DIST = [
  { label: 'Linear',  value: 'linspace' },
  { label: 'Log',     value: 'logspace' },
  { label: 'Values',  value: 'list' }
]
const SPLIT_PRESETS = [60, 70, 75, 80, 85, 90]

const selectedConfigMeta = computed(() =>
  configs.value.find(c => c.id === selectedConfig.value) || null
)
const algorithmMeta = computed(() =>
  selectedConfigMeta.value
    ? registry.value.find(a => a.algorithm === selectedConfigMeta.value.algorithm) || null
    : null
)
const searchableParams = computed(() =>
  algorithmMeta.value ? algorithmMeta.value.params : []
)

const expandValues = (def) => {
  if (!def || !def.enabled) return []
  if (def.kind === 'list') {
    return def.values.split(',').map(s => s.trim()).filter(Boolean)
  }
  const n = Math.max(2, Math.min(50, Number(def.steps) || 5))
  const lo = Number(def.min), hi = Number(def.max)
  if (!isFinite(lo) || !isFinite(hi) || lo === hi) return []
  if (def.kind === 'logspace') {
    if (lo <= 0 || hi <= 0) return []
    const a = Math.log10(lo), b = Math.log10(hi)
    return Array.from({ length: n }, (_, i) => +Math.pow(10, a + (b - a) * i / (n - 1)).toPrecision(4))
  }
  return Array.from({ length: n }, (_, i) => +(lo + (hi - lo) * i / (n - 1)).toPrecision(6))
}

const buildDefaultGrid = (params) => {
  const out = {}
  for (const p of params || []) {
    if (p.type === 'float') {
      out[p.name] = { enabled: false, kind: 'logspace', min: Math.max(p.default * 0.1, 0.001), max: p.default * 10, steps: 5, values: '' }
    } else if (p.type === 'int') {
      const base = p.default ?? 1
      out[p.name] = { enabled: false, kind: 'linspace', min: Math.max(1, Math.round(base / 2)), max: Math.max(base * 2, base + 4), steps: 5, values: '' }
    } else if (p.type === 'bool') {
      out[p.name] = { enabled: false, kind: 'list', values: 'true, false' }
    } else {
      out[p.name] = { enabled: false, kind: 'list', values: String(p.default ?? '') }
    }
  }
  return out
}

watch(selectedConfig, () => { paramGrid.value = buildDefaultGrid(searchableParams.value) }, { immediate: true })

const enabledParamCount = computed(() =>
  Object.values(paramGrid.value).filter(v => v?.enabled).length
)

const combinationCount = computed(() => {
  if (cvSearch.value.mode === 'none') return 0
  const sizes = Object.values(paramGrid.value)
    .filter(v => v.enabled)
    .map(v => expandValues(v).length)
    .filter(n => n > 0)
  if (sizes.length === 0) return 0
  const product = sizes.reduce((a, b) => a * b, 1)
  return cvSearch.value.mode === 'random'
    ? Math.min(product, cvSearch.value.nIter)
    : product
})

const totalFits = computed(() => combinationCount.value * (cvSearch.value.folds || 0))

const gridIncomplete = computed(() =>
  cvSearch.value.mode !== 'none' && enabledParamCount.value > 0 &&
  Object.values(paramGrid.value).some(v => v.enabled && expandValues(v).length === 0)
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

const canLaunch = computed(() =>
  selectedDatasetIds.value.length >= 1 &&
  selectedConfig.value &&
  unjoinable.value.length === 0 &&
  !gridIncomplete.value &&
  !(cvSearch.value.mode !== 'none' && enabledParamCount.value === 0)
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
      dataset_id:      selectedDatasetIds.value[0],
      model_config_id: selectedConfig.value,
      train_split:     trainSplit.value / 100,
      scaler:          scaler.value,
      cv_search:       cvSearch.value.mode !== 'none' ? cvSearch.value : null,
      param_grid:      cvSearch.value.mode !== 'none' ? paramGrid.value : null,
      merge_steps:     mergeSteps.value
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
  await Promise.all([
    datasets.value.length === 0 ? fetchDatasets() : Promise.resolve(),
    configs.value.length  === 0 ? fetchConfigs()  : Promise.resolve()
  ])
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
            <div class="flex flex-wrap gap-1 mt-2">
              <Chip
                v-for="c in d.columns.slice(0, 4)"
                :key="c"
                :label="c"
                class="text-xs"
                style="font-size: 10px; padding: 2px 6px"
              />
              <span v-if="d.columns.length > 4" class="text-xs text-color-secondary self-center">
                +{{ d.columns.length - 4 }}
              </span>
            </div>
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

    <!-- Resulting schema -->
    <div v-if="selectedDatasets.length > 0" class="surface-card border-round shadow-1 p-4 mb-4">
      <h3 class="text-base font-semibold m-0 mb-2">Resulting schema</h3>
      <div v-if="unjoinable.length > 0" class="text-sm text-color-secondary">
        Resolve merge issues above to see the projected schema.
      </div>
      <template v-else>
        <div class="text-sm text-color-secondary mb-3">
          ≈ {{ schema.estimatedRows.toLocaleString() }} rows ·
          {{ schema.columns.length }} column{{ schema.columns.length === 1 ? '' : 's' }}
        </div>
        <div class="flex flex-wrap gap-2">
          <Chip v-for="c in schema.columns" :key="c" :label="c" class="text-xs" />
        </div>
      </template>
    </div>

    <!-- Model configuration -->
    <div class="surface-card border-round shadow-1 mb-4 overflow-hidden">
      <!-- Header -->
      <div class="p-4 border-bottom-1 surface-border">
        <h3 class="text-base font-semibold m-0">Model Configuration</h3>
        <p class="text-xs text-color-secondary m-0 mt-1">Pick a saved model config, then tune the training pipeline.</p>
      </div>

      <!-- Section 1 · Configuration picker -->
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
              <span class="text-xs text-color-secondary uppercase">Target</span>
              <span class="font-mono text-sm">{{ selectedConfigMeta.target_col }}</span>
            </div>
            <Tag
              v-if="algorithmMeta"
              :value="algorithmMeta.family"
              severity="secondary"
              class="text-xs ml-auto"
            />
          </div>
          <span v-if="configOptions.length === 0" class="text-xs text-color-secondary">
            No configurations saved yet — create one in the Models module.
          </span>
        </div>
      </section>

      <Divider class="m-0" />

      <!-- Section 2 · Data split -->
      <section class="p-4 flex flex-column md:flex-row md:align-items-start gap-4">
        <div class="md:w-12rem flex-shrink-0">
          <div class="text-xs font-semibold uppercase text-color-secondary">Data Split</div>
          <div class="text-xs text-color-secondary mt-1">Holdout fraction used to validate the trained model.</div>
        </div>
        <div class="flex-1">
          <!-- Visual proportion bar -->
          <div class="flex w-full border-round overflow-hidden text-xs font-semibold text-white" style="height: 2.25rem">
            <div
              class="flex align-items-center justify-content-center transition-all transition-duration-200"
              :style="{ width: trainSplit + '%', background: 'var(--primary-color)' }"
            >
              Train · {{ trainSplit }}%
            </div>
            <div
              class="flex align-items-center justify-content-center transition-all transition-duration-200"
              :style="{ width: (100 - trainSplit) + '%', background: 'var(--surface-400)' }"
            >
              Val · {{ 100 - trainSplit }}%
            </div>
          </div>

          <!-- Preset chips + precise input -->
          <div class="flex flex-wrap align-items-center gap-2 mt-3">
            <SelectButton
              v-model="trainSplit"
              :options="SPLIT_PRESETS"
              :allowEmpty="false"
            >
              <template #option="{ option }">{{ option }} / {{ 100 - option }}</template>
            </SelectButton>
            <div class="flex align-items-center gap-2 ml-auto">
              <label class="text-xs text-color-secondary">Custom</label>
              <InputNumber
                v-model="trainSplit"
                :min="50" :max="95" suffix="%"
                showButtons buttonLayout="horizontal"
                :step="1"
                decrementButtonClass="p-button-secondary"
                incrementButtonClass="p-button-secondary"
                inputClass="w-4rem text-center"
              />
            </div>
          </div>
        </div>
      </section>

      <Divider class="m-0" />

      <!-- Section 3 · Feature scaler -->
      <section class="p-4 flex flex-column md:flex-row md:align-items-start gap-4">
        <div class="md:w-12rem flex-shrink-0">
          <div class="text-xs font-semibold uppercase text-color-secondary">Feature Scaler</div>
          <div class="text-xs text-color-secondary mt-1">Applied to numeric features. Fit on the train fold only to avoid leakage.</div>
        </div>
        <div class="flex-1">
          <SelectButton
            v-model="scaler"
            :options="SCALER_OPTIONS"
            optionLabel="label"
            optionValue="value"
            :allowEmpty="false"
          />
        </div>
      </section>

      <Divider class="m-0" />

      <!-- Section 4 · Hyperparameter search -->
      <section class="p-4 flex flex-column md:flex-row md:align-items-start gap-4">
        <div class="md:w-12rem flex-shrink-0">
          <div class="text-xs font-semibold uppercase text-color-secondary">Hyperparameter Search</div>
          <div class="text-xs text-color-secondary mt-1">Cross-validated tuning over chosen parameter ranges.</div>
        </div>

        <div class="flex-1 flex flex-column gap-3">
          <SelectButton
            v-model="cvSearch.mode"
            :options="SEARCH_OPTIONS"
            optionLabel="label"
            optionValue="value"
            :allowEmpty="false"
          />

          <div v-if="cvSearch.mode !== 'none'" class="flex flex-column gap-3">
            <!-- CV controls row -->
            <div class="grid m-0 gap-3" :class="cvSearch.mode === 'random' ? 'grid-cols-3' : 'grid-cols-2'">
              <div class="flex flex-column gap-1">
                <label class="font-medium text-xs uppercase text-color-secondary">CV folds</label>
                <InputNumber v-model="cvSearch.folds" :min="2" :max="20" showButtons :useGrouping="false" />
              </div>
              <div v-if="cvSearch.mode === 'random'" class="flex flex-column gap-1">
                <label class="font-medium text-xs uppercase text-color-secondary">n_iter</label>
                <InputNumber v-model="cvSearch.nIter" :min="1" :max="500" showButtons :useGrouping="false" />
              </div>
              <div class="flex flex-column gap-1">
                <label class="font-medium text-xs uppercase text-color-secondary">Scoring</label>
                <Dropdown
                  v-model="cvSearch.scoring"
                  :options="SCORING_OPTIONS"
                  optionLabel="label"
                  optionValue="value"
                  class="w-full"
                />
              </div>
            </div>

            <!-- Parameter grid editor -->
            <div v-if="!selectedConfigMeta" class="surface-ground border-round p-3 text-xs text-color-secondary">
              Select a model configuration to define search ranges.
            </div>
            <div v-else>
              <div class="flex align-items-center justify-content-between mb-2">
                <span class="text-xs font-semibold uppercase text-color-secondary">
                  Parameter ranges
                </span>
                <span class="text-xs text-color-secondary">
                  {{ enabledParamCount }} of {{ searchableParams.length }} enabled
                </span>
              </div>

              <div class="surface-ground border-round overflow-hidden">
                <table class="w-full text-sm" style="border-collapse: collapse">
                  <thead>
                    <tr class="text-xs uppercase text-color-secondary">
                      <th class="text-left p-2" style="width: 3rem"></th>
                      <th class="text-left p-2">Parameter</th>
                      <th class="text-left p-2" style="width: 7rem">Mode</th>
                      <th class="text-left p-2">Range</th>
                      <th class="text-right p-2" style="width: 5rem">Values</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="p in searchableParams"
                      :key="p.name"
                      class="border-top-1 surface-border"
                      :class="paramGrid[p.name]?.enabled ? '' : 'opacity-60'"
                    >
                      <td class="p-2 text-center">
                        <Checkbox v-model="paramGrid[p.name].enabled" :binary="true" />
                      </td>
                      <td class="p-2">
                        <div class="font-mono text-xs text-primary">{{ p.name }}</div>
                        <div class="text-xs text-color-secondary">{{ p.type }} · default {{ p.default ?? 'null' }}</div>
                      </td>
                      <td class="p-2">
                        <Dropdown
                          v-if="p.type === 'float' || p.type === 'int'"
                          v-model="paramGrid[p.name].kind"
                          :options="NUMERIC_DIST"
                          optionLabel="label"
                          optionValue="value"
                          :disabled="!paramGrid[p.name].enabled"
                          class="w-full"
                        />
                        <Tag v-else value="values" severity="secondary" class="text-xs" />
                      </td>
                      <td class="p-2">
                        <template v-if="(p.type === 'float' || p.type === 'int') && paramGrid[p.name].kind !== 'list'">
                          <div class="flex align-items-center gap-2">
                            <InputNumber
                              v-model="paramGrid[p.name].min"
                              :disabled="!paramGrid[p.name].enabled"
                              :useGrouping="false"
                              :minFractionDigits="p.type === 'float' ? 0 : 0"
                              :maxFractionDigits="p.type === 'float' ? 6 : 0"
                              placeholder="min"
                              inputClass="text-xs"
                              class="flex-1"
                            />
                            <span class="text-color-secondary text-xs">→</span>
                            <InputNumber
                              v-model="paramGrid[p.name].max"
                              :disabled="!paramGrid[p.name].enabled"
                              :useGrouping="false"
                              :minFractionDigits="p.type === 'float' ? 0 : 0"
                              :maxFractionDigits="p.type === 'float' ? 6 : 0"
                              placeholder="max"
                              inputClass="text-xs"
                              class="flex-1"
                            />
                            <InputNumber
                              v-model="paramGrid[p.name].steps"
                              :disabled="!paramGrid[p.name].enabled"
                              :min="2" :max="50" :useGrouping="false"
                              showButtons buttonLayout="horizontal"
                              decrementButtonClass="p-button-secondary p-button-text"
                              incrementButtonClass="p-button-secondary p-button-text"
                              inputClass="text-xs w-3rem text-center"
                              v-tooltip.top="'steps'"
                            />
                          </div>
                        </template>
                        <InputText
                          v-else
                          v-model="paramGrid[p.name].values"
                          :disabled="!paramGrid[p.name].enabled"
                          class="w-full text-xs"
                          placeholder="comma-separated, e.g. lbfgs, saga, liblinear"
                        />
                      </td>
                      <td class="p-2 text-right text-xs text-color-secondary font-mono">
                        {{ paramGrid[p.name].enabled ? expandValues(paramGrid[p.name]).length : '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- Search summary -->
              <div class="flex flex-wrap align-items-center gap-2 mt-3">
                <Tag
                  v-if="enabledParamCount === 0"
                  value="No parameters enabled"
                  severity="warning"
                  icon="pi pi-exclamation-triangle"
                />
                <template v-else>
                  <Tag :value="`${combinationCount.toLocaleString()} combinations`" severity="info" />
                  <Tag :value="`${totalFits.toLocaleString()} total fits`" severity="secondary" />
                  <Tag
                    v-if="cvSearch.mode === 'random'"
                    :value="`sampling ${cvSearch.nIter} of search space`"
                    severity="secondary"
                  />
                  <Tag
                    v-if="gridIncomplete"
                    value="Some ranges are invalid"
                    severity="danger"
                    icon="pi pi-times-circle"
                  />
                </template>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <div class="flex gap-2">
      <Button label="Launch" icon="pi pi-play" :loading="submitting" :disabled="!canLaunch" @click="launch" />
      <Button label="Cancel" severity="secondary" text @click="router.push({ name: 'calibrate_jobs' })" />
    </div>
  </div>
</template>
