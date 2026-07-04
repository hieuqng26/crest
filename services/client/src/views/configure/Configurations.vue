<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { useToast } from 'primevue/usetoast'
import { FilterMatchMode } from 'primevue/api'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import { configs, registry, fetchConfigs, addConfig, updateConfig, duplicateConfig, deleteConfig, bulkDeleteConfigs } from './configsStore'
import { fmtDate } from '@/utils/datetime'

const route = useRoute()
const router = useRouter()
const store = useStore()
const toast = useToast()

const canWrite = computed(() => store.getters.can('model_config:write'))

const FAMILY_LABEL    = { classification: 'Classification', ensemble: 'Ensemble', regression: 'Regression', timeseries: 'Time Series', statistical: 'Statistical' }
const FAMILY_SEVERITY = { classification: 'info', ensemble: 'warning', regression: 'success', timeseries: 'contrast', statistical: 'secondary' }

const SCALER_OPTIONS = [
  { label: 'None',     value: 'none' },
  { label: 'Standard', value: 'standard' },
  { label: 'Min-Max',  value: 'minmax' },
  { label: 'Robust',   value: 'robust' }
]
const SEARCH_OPTIONS = [
  { label: 'None',       value: 'none' },
  { label: 'Grid',       value: 'grid' },
  { label: 'Randomized', value: 'random' }
]
const SCORING_OPTIONS = [
  { label: 'ROC AUC', value: 'roc_auc' },
  { label: 'Accuracy', value: 'accuracy' },
  { label: 'F1',       value: 'f1' },
  { label: 'Neg. MSE', value: 'neg_mean_squared_error' },
  { label: 'R²',       value: 'r2' }
]
const NUMERIC_DIST = [
  { label: 'Linear', value: 'linspace' },
  { label: 'Log',    value: 'logspace' },
  { label: 'Values', value: 'list' }
]
const SPLIT_PRESETS = [
  { label: '60/40', value: 60 },
  { label: '70/30', value: 70 },
  { label: '75/25', value: 75 },
  { label: '80/20', value: 80 },
  { label: '85/15', value: 85 },
  { label: '90/10', value: 90 },
]

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
      out[p.name] = { enabled: false, kind: 'logspace', min: Math.max((p.default ?? 0.1) * 0.1, 0.001), max: Math.max((p.default ?? 1) * 10, 0.01), steps: 5, values: '' }
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

const algorithmOptions = computed(() => [
  { label: 'All algorithms', value: null },
  ...registry.value.map(a => ({ label: `${a.algorithm} (${FAMILY_LABEL[a.family] ?? a.family})`, value: a.algorithm }))
])
const familyOptions = [
  { label: 'All',            value: null },
  { label: 'Classification', value: 'classification' },
  { label: 'Ensemble',       value: 'ensemble' },
  { label: 'Regression',     value: 'regression' },
  { label: 'Time Series',    value: 'timeseries' },
  { label: 'Statistical',    value: 'statistical' }
]

const algorithmFilter = ref(route.query.algorithm || null)
const familyFilter = ref(null)
const filters = ref({ global: { value: '', matchMode: FilterMatchMode.CONTAINS } })

const algoFamily = (algoName) => registry.value.find(a => a.algorithm === algoName)?.family

const filteredRows = computed(() =>
  configs.value.filter(c =>
    (!algorithmFilter.value || c.algorithm === algorithmFilter.value) &&
    (!familyFilter.value || algoFamily(c.algorithm) === familyFilter.value) &&
    (!filters.value.global.value ||
      ['name', 'algorithm', 'created_by'].some(f =>
        String(c[f] ?? '').toLowerCase().includes(filters.value.global.value.toLowerCase())
      )
    )
  )
)

// ---- Dialog (create + edit + view) ----
const dialogVisible = ref(false)
const editingId = ref(null)
const viewOnly = ref(false)
const form = ref({
  name: '',
  algorithm: null,
  hyperparams: {},
  trainSplit: 80,
  scaler: 'none',
  cvSearch: { mode: 'none', folds: 5, nIter: 20, scoring: 'roc_auc' },
  paramGrid: {}
})
const saving = ref(false)

const selectedAlgoMeta = computed(() =>
  registry.value.find(a => a.algorithm === form.value.algorithm) || null
)

const formSearchableParams = computed(() => selectedAlgoMeta.value?.params ?? [])

const enabledParamCount = computed(() =>
  Object.values(form.value.paramGrid).filter(v => v?.enabled).length
)

const combinationCount = computed(() => {
  if (form.value.cvSearch.mode === 'none') return 0
  const sizes = Object.values(form.value.paramGrid)
    .filter(v => v.enabled)
    .map(v => expandValues(v).length)
    .filter(n => n > 0)
  if (!sizes.length) return 0
  const product = sizes.reduce((a, b) => a * b, 1)
  return form.value.cvSearch.mode === 'random' ? Math.min(product, form.value.cvSearch.nIter) : product
})

const gridIncomplete = computed(() =>
  form.value.cvSearch.mode !== 'none' && enabledParamCount.value > 0 &&
  Object.values(form.value.paramGrid).some(v => v.enabled && expandValues(v).length === 0)
)

const defaultScoringForFamily = (family) =>
  family === 'classification' ? 'roc_auc' : 'r2'

watch(() => form.value.algorithm, (algo, prev) => {
  if (algo === prev) return
  const meta = registry.value.find(a => a.algorithm === algo)
  form.value.hyperparams = meta
    ? meta.params.reduce((acc, p) => (acc[p.name] = p.default, acc), {})
    : {}
  form.value.paramGrid = buildDefaultGrid(meta?.params ?? [])
  form.value.cvSearch.scoring = defaultScoringForFamily(meta?.family)
})

const openCreate = (presetAlgorithm = null) => {
  viewOnly.value = false
  editingId.value = null
  const algo = presetAlgorithm || algorithmFilter.value || null
  const meta = registry.value.find(a => a.algorithm === algo)
  form.value = {
    name: '',
    algorithm: algo,
    hyperparams: {},
    trainSplit: 80,
    scaler: 'none',
    cvSearch: { mode: 'none', folds: 5, nIter: 20, scoring: defaultScoringForFamily(meta?.family) },
    paramGrid: {}
  }
  dialogVisible.value = true
}

const openView = (cfg) => { viewOnly.value = true; openEdit(cfg) }

const openEdit = (cfg) => {
  viewOnly.value = false
  editingId.value = cfg.id
  const params = cfg.hyperparams_json ? JSON.parse(cfg.hyperparams_json) : {}
  const searchCfg = cfg.search_config_json ? JSON.parse(cfg.search_config_json) : null
  form.value = {
    name: cfg.name,
    algorithm: cfg.algorithm,
    hyperparams: params,
    trainSplit: Math.round((cfg.train_split ?? 0.8) * 100),
    scaler: cfg.scaler ?? 'none',
    cvSearch: {
      mode: searchCfg?.mode ?? 'none',
      folds: searchCfg?.folds ?? 5,
      nIter: searchCfg?.nIter ?? 20,
      scoring: searchCfg?.scoring ?? 'roc_auc'
    },
    paramGrid: searchCfg?.paramGrid ?? buildDefaultGrid(
      registry.value.find(a => a.algorithm === cfg.algorithm)?.params ?? []
    )
  }
  dialogVisible.value = true
}

const saveConfig = async () => {
  if (!form.value.name.trim()) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Config name is required', life: 3000 }); return
  }
  if (!form.value.algorithm) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Algorithm is required', life: 3000 }); return
  }
  saving.value = true
  const body = {
    name: form.value.name,
    algorithm: form.value.algorithm,
    hyperparams: form.value.hyperparams,
    train_split: form.value.trainSplit / 100,
    scaler: form.value.scaler === 'none' ? null : form.value.scaler,
    search_config: form.value.cvSearch.mode !== 'none' ? {
      mode: form.value.cvSearch.mode,
      folds: form.value.cvSearch.folds,
      nIter: form.value.cvSearch.nIter,
      scoring: form.value.cvSearch.scoring,
      paramGrid: form.value.paramGrid
    } : null
  }
  try {
    if (editingId.value) {
      const data = await updateConfig(editingId.value, body)
      toast.add({ severity: 'success', summary: 'Updated', detail: `"${data.name}" saved`, life: 2500 })
    } else {
      const { data } = await modelConfigsAPI.create(body)
      addConfig(data)
      toast.add({ severity: 'success', summary: 'Created', detail: `"${data.name}" saved`, life: 2500 })
    }
    dialogVisible.value = false
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Save failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    saving.value = false
  }
}

// ---- Row actions ----
const calibrate = (cfg) => router.push({ name: 'calibrate_new', query: { config_id: cfg.id } })

const onDuplicate = async (cfg) => {
  try {
    const row = await duplicateConfig(cfg)
    toast.add({ severity: 'info', summary: 'Duplicated', detail: row.name, life: 2000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Error', detail: e.message, life: 5000 })
  }
}

// ---- Delete dialog ----
const deleteDialog      = ref(false)
const deleteTarget      = ref(null)
const deleteRefs        = ref([])
const deleteRefsLoading = ref(false)
const deleteConfirming  = ref(false)

async function openDeleteDialog(cfg) {
  deleteTarget.value      = cfg
  deleteRefs.value        = []
  deleteDialog.value      = true
  deleteRefsLoading.value = true
  try {
    const { data } = await modelConfigsAPI.refs(cfg.id)
    deleteRefs.value = data.calibration_runs ?? []
  } catch { /* non-critical */ }
  finally { deleteRefsLoading.value = false }
}

async function confirmDelete() {
  deleteConfirming.value = true
  try {
    await deleteConfig(deleteTarget.value.id)
    deleteDialog.value = false
    toast.add({ severity: 'success', summary: 'Deleted', detail: deleteTarget.value.name, life: 2000 })
  } catch (e) {
    const detail = e?.response?.data?.message ?? e?.response?.data?.error ?? e.message
    toast.add({ severity: 'error', summary: 'Delete failed', detail, life: 5000 })
  } finally {
    deleteConfirming.value = false
  }
}

// ---- Bulk delete ----
const selectMode = ref(false)
const selection = ref([])
const confirmingBulkDelete = ref(false)

const exitSelectMode = () => {
  selectMode.value = false
  selection.value = []
  confirmingBulkDelete.value = false
}

const bulkDelete = async () => {
  try {
    const data = await bulkDeleteConfigs(selection.value.map(c => c.id))
    toast.add({ severity: 'success', summary: 'Deleted', detail: `${data.deleted} configuration${data.deleted !== 1 ? 's' : ''} deleted`, life: 3000 })
  } catch (e) {
    const detail = e?.response?.data?.message ?? e?.response?.data?.error ?? e.message
    toast.add({ severity: 'error', summary: 'Delete failed', detail, life: 5000 })
  }
  exitSelectMode()
}

onMounted(async () => {
  await fetchConfigs()
  if (route.query.new === '1') {
    openCreate(route.query.algorithm || null)
  } else if (route.query.config_id) {
    const cfg = configs.value.find(c => c.id === Number(route.query.config_id))
    if (cfg) openView(cfg)
  }
})
</script>

<template>
  <div class="p-4">
    <div class="flex align-items-center justify-content-between mb-4">
      <div>
        <h2 class="text-2xl font-semibold m-0">Saved Configurations</h2>
        <p class="text-color-secondary text-sm m-0 mt-1">Model configurations ready to calibrate.</p>
      </div>
    </div>

    <div class="surface-card border-round shadow-1 p-4">
      <div class="flex flex-wrap align-items-center gap-3 mb-3">
        <IconField class="flex-1" style="min-width: 16rem">
          <InputIcon class="pi pi-search" />
          <InputText v-model="filters.global.value" placeholder="Search configurations…" class="w-full" />
        </IconField>
        <Dropdown
          v-model="algorithmFilter"
          :options="algorithmOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="Algorithm"
          class="w-15rem"
          showClear
        />
        <Dropdown
          v-model="familyFilter"
          :options="familyOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="All families"
          class="w-11rem"
        />

        <template v-if="!selectMode">
          <Button label="Select" icon="pi pi-check-square" size="small" severity="secondary" text @click="selectMode = true" />
        </template>
        <template v-else>
          <span class="text-sm text-color-secondary">{{ selection.length }} selected</span>
          <template v-if="!confirmingBulkDelete">
            <Button
              label="Delete selected"
              icon="pi pi-trash"
              size="small"
              severity="danger"
              :disabled="selection.length === 0"
              @click="confirmingBulkDelete = true"
            />
          </template>
          <template v-else>
            <span class="text-sm font-medium text-red-400">Delete {{ selection.length }} config{{ selection.length !== 1 ? 's' : '' }}?</span>
            <Button label="Confirm" icon="pi pi-check" size="small" severity="danger" @click="bulkDelete" />
            <Button label="Cancel"  size="small" severity="secondary" text @click="confirmingBulkDelete = false" />
          </template>
          <Button icon="pi pi-times" size="small" severity="secondary" text rounded @click="exitSelectMode" v-tooltip.top="'Exit select mode'" />
        </template>
      </div>

      <DataTable
        :value="filteredRows"
        v-model:selection="selection"
        :selectionMode="selectMode ? 'multiple' : null"
        dataKey="id"
        size="small"
        :paginator="filteredRows.length > 10"
        :rows="10"
      >
        <template #empty>
          <div class="text-center p-4 text-color-secondary">
            <i class="pi pi-inbox text-3xl block mb-2" />
            <p class="m-0">No configurations match your filters.</p>
          </div>
        </template>

        <Column v-if="selectMode" selectionMode="multiple" style="width: 3rem" />
        <Column field="id" header="ID" style="width:4rem" />
        <Column field="name" header="Name" sortable />
        <Column header="Algorithm" sortable sortField="algorithm">
          <template #body="{ data }">
            <span class="font-mono text-sm">{{ data.algorithm }}</span>
          </template>
        </Column>
        <Column header="Family" sortable :sortField="(d) => algoFamily(d.algorithm)">
          <template #body="{ data }">
            <Tag
              v-if="algoFamily(data.algorithm)"
              :value="FAMILY_LABEL[algoFamily(data.algorithm)]"
              :severity="FAMILY_SEVERITY[algoFamily(data.algorithm)]"
              class="text-xs"
            />
          </template>
        </Column>
        <Column field="created_by" header="Created By" sortable />
        <Column field="created_at" header="Date" sortable style="width:12rem">
          <template #body="{ data }">{{ fmtDate(data.created_at) }}</template>
        </Column>
        <Column v-if="!selectMode" header="" style="width:12rem">
          <template #body="{ data }">
            <div class="flex gap-1 justify-content-end">
              <Button icon="pi pi-play"   text rounded size="small" v-tooltip.top="'Calibrate'" v-can="'calibration:execute'" @click="calibrate(data)" />
              <Button v-if="canWrite" icon="pi pi-pencil" text rounded size="small" v-tooltip.top="'Edit'"      @click="openEdit(data)" />
              <Button v-else          icon="pi pi-eye"    text rounded size="small" v-tooltip.top="'View'"      @click="openView(data)" />
              <Button icon="pi pi-copy"  text rounded size="small" v-tooltip.top="'Duplicate'" v-can="'model_config:write'" @click="onDuplicate(data)" />
              <Button icon="pi pi-trash" text rounded size="small" severity="danger" v-tooltip.top="'Delete'" v-can="'model_config:write'" @click="openDeleteDialog(data)" />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <!-- Create / Edit dialog -->
    <Dialog v-model:visible="dialogVisible" modal :style="{ width: 'min(56rem, 90vw)' }" :draggable="false">
      <template #header>
        <div class="text-lg font-semibold">
          {{ viewOnly ? 'View Configuration' : editingId ? 'Edit Configuration' : 'New Configuration' }}
        </div>
      </template>

      <div class="flex flex-column gap-4" :style="{ maxHeight: '70vh', overflowY: 'auto', paddingRight: '0.25rem', pointerEvents: viewOnly ? 'none' : 'auto', userSelect: viewOnly ? 'none' : 'auto' }">
        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Config Name</label>
          <InputText v-model="form.name" placeholder="e.g. PD_LR_2024_Q4" class="w-full" />
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Algorithm</label>
          <Dropdown
            v-model="form.algorithm"
            :options="algorithmOptions.filter(o => o.value)"
            optionLabel="label"
            optionValue="value"
            placeholder="Select algorithm"
            class="w-full"
            :disabled="!!editingId"
          />
          <span v-if="selectedAlgoMeta" class="text-xs text-color-secondary mt-1">{{ selectedAlgoMeta.description }}</span>
        </div>

        <div v-if="selectedAlgoMeta" class="flex flex-column gap-2">
          <label class="font-medium text-sm">Hyperparameters</label>
          <div v-for="p in selectedAlgoMeta.params" :key="p.name" class="flex flex-column gap-1">
            <div class="flex align-items-center justify-content-between">
              <span class="font-mono text-xs text-primary">{{ p.name }}</span>
              <span class="text-xs text-color-secondary">{{ p.type }}</span>
            </div>
            <InputText
              v-if="p.type === 'string'"
              v-model="form.hyperparams[p.name]"
              class="w-full"
              :placeholder="String(p.default)"
            />
            <InputNumber
              v-else-if="p.type === 'float' || p.type === 'int'"
              v-model="form.hyperparams[p.name]"
              :useGrouping="false"
              :minFractionDigits="p.type === 'float' ? 1 : 0"
              :maxFractionDigits="p.type === 'float' ? 6 : 0"
              class="w-full"
              fluid
            />
            <InputSwitch v-else-if="p.type === 'bool'" v-model="form.hyperparams[p.name]" />
            <span v-if="p.description && p.description !== p.name" class="text-xs text-color-secondary">{{ p.description }}</span>
          </div>
        </div>

        <Divider />

        <!-- Data Split -->
        <div class="flex flex-column gap-2">
          <label class="section-label">Data Split</label>
          <Slider
            v-model="form.trainSplit"
            :min="50" :max="95" :step="1"
            class="split-slider"
          />
          <div class="flex align-items-center justify-content-between text-xs text-color-secondary mt-1">
            <span><span class="dot dot-train" /> Train · <span class="font-semibold text-color">{{ form.trainSplit }}%</span></span>
            <span><span class="dot dot-val" /> Val · <span class="font-semibold text-color">{{ 100 - form.trainSplit }}%</span></span>
          </div>
          <div class="seg-group mt-1">
            <button
              v-for="o in SPLIT_PRESETS"
              :key="o.value"
              type="button"
              class="seg-pill"
              :class="{ 'is-active': form.trainSplit === o.value }"
              @click="form.trainSplit = o.value"
            >{{ o.label }}</button>
          </div>
        </div>

        <Divider />

        <!-- Feature Scaler -->
        <div class="flex flex-column gap-2">
          <label class="section-label">Feature Scaler</label>
          <div class="seg-group">
            <button
              v-for="o in SCALER_OPTIONS"
              :key="o.value"
              type="button"
              class="seg-pill"
              :class="{ 'is-active': form.scaler === o.value }"
              @click="form.scaler = o.value"
            >{{ o.label }}</button>
          </div>
        </div>

        <Divider />

        <!-- Hyperparameter Search -->
        <div class="flex flex-column gap-3">
          <label class="section-label">Hyperparameter Search</label>
          <div class="seg-group">
            <button
              v-for="o in SEARCH_OPTIONS"
              :key="o.value"
              type="button"
              class="seg-pill"
              :class="{ 'is-active': form.cvSearch.mode === o.value }"
              @click="form.cvSearch.mode = o.value"
            >{{ o.label }}</button>
          </div>
          <div v-if="form.cvSearch.mode !== 'none'" class="flex flex-column gap-3">
            <div class="flex gap-3">
              <div class="flex flex-column gap-1 flex-1">
                <label class="text-xs text-color-secondary uppercase tracking-wide">CV Folds</label>
                <InputNumber v-model="form.cvSearch.folds" :min="2" :max="20" showButtons buttonLayout="stacked" :useGrouping="false"
                  decrementButtonClass="num-btn" incrementButtonClass="num-btn" inputClass="num-input" />
              </div>
              <div v-if="form.cvSearch.mode === 'random'" class="flex flex-column gap-1 flex-1">
                <label class="text-xs text-color-secondary uppercase tracking-wide">n_iter</label>
                <InputNumber v-model="form.cvSearch.nIter" :min="1" :max="500" showButtons buttonLayout="stacked" :useGrouping="false"
                  decrementButtonClass="num-btn" incrementButtonClass="num-btn" inputClass="num-input" />
              </div>
              <div class="flex flex-column gap-1 flex-1">
                <label class="text-xs text-color-secondary uppercase tracking-wide">Scoring</label>
                <Dropdown v-model="form.cvSearch.scoring" :options="SCORING_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
              </div>
            </div>

            <!-- Parameter grid table -->
            <div v-if="!form.algorithm" class="text-xs text-color-secondary">Select an algorithm first.</div>
            <div v-else>
              <div class="flex align-items-center justify-content-between mb-1">
                <span class="text-xs font-semibold uppercase text-color-secondary">Parameter Ranges</span>
                <span class="text-xs text-color-secondary">{{ enabledParamCount }} of {{ formSearchableParams.length }} enabled · {{ combinationCount.toLocaleString() }} combos</span>
              </div>
              <div class="surface-ground border-round overflow-hidden">
                <table class="w-full text-sm" style="border-collapse: collapse">
                  <thead>
                    <tr class="text-xs uppercase text-color-secondary">
                      <th class="text-left p-2" style="width:2.5rem"></th>
                      <th class="text-left p-2">Parameter</th>
                      <th class="text-left p-2" style="width:6rem">Mode</th>
                      <th class="text-left p-2">Range / Values</th>
                      <th class="text-right p-2" style="width:4rem">#</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="p in formSearchableParams"
                      :key="p.name"
                      class="border-top-1 surface-border"
                      :class="form.paramGrid[p.name]?.enabled ? '' : 'opacity-60'"
                    >
                      <td class="p-2 text-center">
                        <Checkbox v-if="form.paramGrid[p.name]" v-model="form.paramGrid[p.name].enabled" :binary="true" />
                      </td>
                      <td class="p-2">
                        <div class="font-mono text-xs text-primary">{{ p.name }}</div>
                        <div class="text-xs text-color-secondary">{{ p.type }} · {{ p.default ?? 'null' }}</div>
                      </td>
                      <td class="p-2">
                        <Dropdown
                          v-if="form.paramGrid[p.name] && (p.type === 'float' || p.type === 'int')"
                          v-model="form.paramGrid[p.name].kind"
                          :options="NUMERIC_DIST"
                          optionLabel="label"
                          optionValue="value"
                          :disabled="!form.paramGrid[p.name]?.enabled"
                          class="w-full"
                        />
                        <Tag v-else value="values" severity="secondary" class="text-xs" />
                      </td>
                      <td class="p-2">
                        <template v-if="form.paramGrid[p.name] && (p.type === 'float' || p.type === 'int') && form.paramGrid[p.name].kind !== 'list'">
                          <div class="flex align-items-center gap-2">
                            <InputNumber
                              v-model="form.paramGrid[p.name].min"
                              :disabled="!form.paramGrid[p.name]?.enabled"
                              :useGrouping="false"
                              :maxFractionDigits="p.type === 'float' ? 6 : 0"
                              placeholder="min"
                              inputClass="range-input"
                              class="flex-1"
                            />
                            <span class="text-color-secondary text-xs">→</span>
                            <InputNumber
                              v-model="form.paramGrid[p.name].max"
                              :disabled="!form.paramGrid[p.name]?.enabled"
                              :useGrouping="false"
                              :maxFractionDigits="p.type === 'float' ? 6 : 0"
                              placeholder="max"
                              inputClass="range-input"
                              class="flex-1"
                            />
                            <span class="text-xs text-color-secondary">in</span>
                            <InputNumber
                              v-model="form.paramGrid[p.name].steps"
                              :disabled="!form.paramGrid[p.name]?.enabled"
                              :min="2"
                              :max="50"
                              :useGrouping="false"
                              inputClass="step-input"
                              v-tooltip.top="'Steps'"
                            />
                            <span class="text-xs text-color-secondary">steps</span>
                          </div>
                        </template>
                        <InputText
                          v-else-if="form.paramGrid[p.name]"
                          v-model="form.paramGrid[p.name].values"
                          :disabled="!form.paramGrid[p.name]?.enabled"
                          class="w-full text-xs"
                          placeholder="comma-separated"
                        />
                      </td>
                      <td class="p-2 text-right text-xs font-mono text-color-secondary">
                        {{ form.paramGrid[p.name]?.enabled ? expandValues(form.paramGrid[p.name]).length : '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="gridIncomplete" class="mt-2">
                <Tag value="Some ranges are invalid" severity="danger" icon="pi pi-times-circle" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <Button label="Close" severity="secondary" text @click="dialogVisible = false" />
        <Button
          v-if="!viewOnly"
          :label="editingId ? 'Save Changes' : 'Save Configuration'"
          icon="pi pi-save"
          :loading="saving"
          @click="saveConfig"
        />
      </template>
    </Dialog>

    <!-- Delete confirm dialog -->
    <Dialog v-model:visible="deleteDialog" modal :style="{ width: '32rem' }" :draggable="false" header="Delete configuration">
      <div class="flex flex-column gap-3">
        <p class="m-0 text-sm">
          Are you sure you want to delete
          <span class="font-semibold">{{ deleteTarget?.name }}</span>?
          This cannot be undone.
        </p>

        <div v-if="deleteRefsLoading" class="flex align-items-center gap-2 text-sm text-color-secondary">
          <i class="pi pi-spin pi-spinner" /> Checking dependencies…
        </div>

        <div v-else-if="deleteRefs.length" class="flex flex-column gap-2">
          <div class="text-sm font-semibold text-red-400 flex align-items-center gap-2">
            <i class="pi pi-exclamation-triangle" />
            Cannot delete — referenced by {{ deleteRefs.length }} calibration job(s):
          </div>
          <div class="flex flex-column gap-1 pl-2">
            <div v-for="run in deleteRefs" :key="run.run_id" class="flex align-items-center gap-2 text-sm">
              <span class="dot-status" :style="{ background: { queued: '#60a5fa', running: '#facc15', success: '#34d399', failed: '#f87171' }[run.status] ?? 'var(--surface-400)' }" />
              <a class="text-primary cursor-pointer hover:underline font-mono text-xs"
                @click="router.push({ name: 'jobs_detail', params: { kind: 'training', run_id: run.run_id } }); deleteDialog = false">
                {{ run.run_id.slice(0, 16) }}…
              </a>
              <span class="text-xs text-color-secondary capitalize">({{ run.status }})</span>
              <span v-if="run.target_col" class="text-xs text-color-secondary font-mono">· {{ run.target_col }}</span>
            </div>
          </div>
          <p class="m-0 text-xs text-color-secondary">Delete those calibration jobs first, then retry.</p>
        </div>
      </div>

      <template #footer>
        <Button label="Cancel" severity="secondary" text @click="deleteDialog = false" />
        <Button
          label="Delete"
          icon="pi pi-trash"
          severity="danger"
          :disabled="deleteRefsLoading || deleteRefs.length > 0"
          :loading="deleteConfirming"
          @click="confirmDelete"
        />
      </template>
    </Dialog>
  </div>
</template>

<style scoped>
.dot-status {
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.section-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

/* Segmented pill control */
.seg-group {
  display: inline-flex;
  align-self: flex-start;
  width: fit-content;
  background: var(--surface-ground);
  border: 1px solid var(--surface-border);
  border-radius: 999px;
  padding: 3px;
  gap: 2px;
}
.seg-pill {
  display: inline-flex;
  align-items: center;
  padding: 5px 14px;
  border-radius: 999px;
  border: 0;
  background: transparent;
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
  font-variant-numeric: tabular-nums;
}
.seg-pill:hover { color: var(--text-color); }
.seg-pill.is-active {
  background: var(--surface-card);
  color: var(--text-color);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.18);
}

.dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.dot-train { background: var(--primary-color); }
.dot-val { background: var(--surface-400); }

/* Data split slider — slim flat look */
.split-slider :deep(.p-slider) {
  background: var(--surface-ground);
  border: 1px solid var(--surface-border);
  border-radius: 999px;
  height: 6px;
}
.split-slider :deep(.p-slider-range) {
  background: var(--primary-color);
  border-radius: 999px;
}
.split-slider :deep(.p-slider-handle) {
  width: 16px;
  height: 16px;
  background: var(--primary-color);
  border: 2px solid var(--surface-card);
  margin-top: -7px;
  margin-left: -8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  transition: transform 120ms ease;
}
.split-slider :deep(.p-slider-handle:hover) {
  transform: scale(1.15);
}
.split-slider :deep(.p-slider-handle:focus) { box-shadow: 0 0 0 3px rgba(255, 230, 0, 0.25); }

/* Parameter range row inputs */
:deep(.range-input) {
  font-size: 0.8125rem;
  padding: 6px 8px;
  text-align: left;
  font-variant-numeric: tabular-nums;
}
:deep(.step-input) {
  width: 3.25rem;
  font-size: 0.875rem;
  padding: 6px 4px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* Tone down InputNumber spinner buttons (num-btn class) */
:deep(.num-btn) {
  background: var(--surface-ground) !important;
  color: var(--text-color-secondary) !important;
  border: 1px solid var(--surface-border) !important;
  border-left: 0 !important;
  width: 1.8rem !important;
  box-shadow: none !important;
}
:deep(.num-btn:hover) {
  background: var(--surface-border) !important;
  color: var(--text-color) !important;
}
:deep(.num-btn:focus) { box-shadow: none !important; outline: none !important; }
:deep(.num-input) {
  text-align: center;
  font-variant-numeric: tabular-nums;
}
</style>
