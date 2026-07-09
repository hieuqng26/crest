<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import { configs, registry, fetchConfigs } from './newModelStore'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseTable from '@/views/composables/BaseTable.vue'
import SplitSlider from '@/components/ui/SplitSlider.vue'
import { fmtDate } from '@/utils/datetime'

const route = useRoute()
const toast = useToast()
const confirm = useConfirm()

const FAMILY_LABEL = { classification: 'Classification', ensemble: 'Ensemble', regression: 'Regression', timeseries: 'Time Series', statistical: 'Statistical' }
const FAMILY_ORDER = ['regression', 'ensemble', 'classification', 'timeseries', 'statistical']

const loading = ref(true)
onMounted(async () => {
  loading.value = true
  try {
    await fetchConfigs()
    if (route.query.new === '1') openCreate(route.query.algorithm || null)
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loading.value = false
  }
})

// ── Algorithm sidebar filter ──────────────────────────────────────────────────
const algoFilter = ref('All')
const search = ref('')

const countByAlgo = (algo) => configs.value.filter((c) => c.algorithm === algo).length
const algoTree = computed(() =>
  FAMILY_ORDER
    .map((fam) => ({
      label: FAMILY_LABEL[fam].toUpperCase(),
      algos: registry.value.filter((a) => a.family === fam).map((a) => ({ name: a.algorithm, count: countByAlgo(a.algorithm) }))
    }))
    .filter((f) => f.algos.length)
)

const filteredConfigs = computed(() => {
  const q = search.value.trim().toLowerCase()
  return configs.value
    .filter((c) => algoFilter.value === 'All' || c.algorithm === algoFilter.value)
    .filter((c) => !q || (c.name + c.algorithm).toLowerCase().includes(q))
})

const settingsSummary = (c) => {
  const split = Math.round((c.train_split ?? 0.8) * 100)
  const scaler = c.scaler ? c.scaler[0].toUpperCase() + c.scaler.slice(1) : 'No scaler'
  const search = c.search_config_json ? JSON.parse(c.search_config_json) : null
  const searchLabel = search && search.mode !== 'none' ? ` · ${search.mode} search` : ''
  return `${split}/${100 - split} · ${scaler} · ${c.split_by} ≤${c.max_segments}${searchLabel}`
}

const CONFIG_COLS = [
  { field: 'name', label: 'NAME', width: '18%' },
  { field: 'algorithm', label: 'ALGORITHM', width: '140px' },
  { field: 'settings', label: 'SETTINGS', width: '28%' },
  { field: 'used_by', label: 'USED BY', width: '110px' },
  { field: 'updated', label: 'UPDATED', width: '150px' },
  { field: 'actions', label: 'ACTIONS', width: '200px', align: 'right' },
]

// ── Editor ────────────────────────────────────────────────────────────────────
const editing = ref(null) // null | 'new' | configId
const editorOpen = computed(() => editing.value !== null)
const editorTitle = computed(() => (editing.value === 'new' ? 'NEW CONFIGURATION' : 'EDIT CONFIGURATION'))
const saving = ref(false)

const SCALER_OPTIONS = ['None', 'Standard', 'Min-Max', 'Robust']
const SEARCH_MODES = ['None', 'Grid', 'Randomized']
const SCORING_OPTIONS = [
  { label: 'R²', value: 'r2' },
  { label: 'Neg. MSE', value: 'neg_mean_squared_error' },
  { label: 'ROC AUC', value: 'roc_auc' },
  { label: 'Accuracy', value: 'accuracy' },
  { label: 'F1', value: 'f1' }
]

const form = ref({
  name: '', algorithm: null, hyperparams: {},
  trainPct: 100, scaler: 'None', splitBy: 'Subsector', maxSeg: 5,
  cvSearch: { mode: 'None', folds: 5, nIter: 20, scoring: 'r2' },
  paramGrid: {}
})

function buildDefaultGrid(params) {
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
function expandValues(def) {
  if (!def || !def.enabled) return []
  if (def.kind === 'list') return def.values.split(',').map((s) => s.trim()).filter(Boolean)
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
const selectedAlgoMeta = computed(() => registry.value.find((a) => a.algorithm === form.value.algorithm) || null)
const enabledParamCount = computed(() => Object.values(form.value.paramGrid).filter((v) => v?.enabled).length)
const combinationCount = computed(() => {
  if (form.value.cvSearch.mode === 'None') return 0
  const sizes = Object.values(form.value.paramGrid).filter((v) => v.enabled).map((v) => expandValues(v).length).filter((n) => n > 0)
  if (!sizes.length) return 0
  const product = sizes.reduce((a, b) => a * b, 1)
  return form.value.cvSearch.mode === 'Randomized' ? Math.min(product, form.value.cvSearch.nIter) : product
})

watch(() => form.value.algorithm, (algo, prev) => {
  if (algo === prev) return
  const meta = registry.value.find((a) => a.algorithm === algo)
  form.value.hyperparams = meta ? meta.params.reduce((acc, p) => (acc[p.name] = p.default, acc), {}) : {}
  form.value.paramGrid = buildDefaultGrid(meta?.params ?? [])
})

const openCreate = (presetAlgorithm = null) => {
  editing.value = 'new'
  const algo = presetAlgorithm || (algoFilter.value !== 'All' ? algoFilter.value : registry.value[0]?.algorithm) || null
  const meta = registry.value.find((a) => a.algorithm === algo)
  form.value = {
    name: '', algorithm: algo, hyperparams: meta ? meta.params.reduce((acc, p) => (acc[p.name] = p.default, acc), {}) : {},
    trainPct: 100, scaler: 'None', splitBy: 'Subsector', maxSeg: 5,
    cvSearch: { mode: 'None', folds: 5, nIter: 20, scoring: 'r2' },
    paramGrid: buildDefaultGrid(meta?.params ?? [])
  }
}
const openEdit = (cfg) => {
  editing.value = cfg.id
  const params = cfg.hyperparams_json ? JSON.parse(cfg.hyperparams_json) : {}
  const searchCfg = cfg.search_config_json ? JSON.parse(cfg.search_config_json) : null
  form.value = {
    name: cfg.name, algorithm: cfg.algorithm, hyperparams: params,
    trainPct: Math.round((cfg.train_split ?? 0.8) * 100),
    scaler: cfg.scaler ? cfg.scaler[0].toUpperCase() + cfg.scaler.slice(1) : 'None',
    splitBy: cfg.split_by === 'country' ? 'Country' : 'Subsector',
    maxSeg: cfg.max_segments ?? 5,
    cvSearch: {
      mode: searchCfg?.mode === 'grid' ? 'Grid' : searchCfg?.mode === 'random' ? 'Randomized' : 'None',
      folds: searchCfg?.folds ?? 5, nIter: searchCfg?.nIter ?? 20, scoring: searchCfg?.scoring ?? 'r2'
    },
    paramGrid: searchCfg?.paramGrid ?? buildDefaultGrid(registry.value.find((a) => a.algorithm === cfg.algorithm)?.params ?? [])
  }
}
const cancelEdit = () => { editing.value = null }

const saveConfig = async () => {
  if (!form.value.name.trim()) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Configuration name is required', life: 3000 }); return
  }
  saving.value = true
  const body = {
    name: form.value.name.trim(),
    algorithm: form.value.algorithm,
    hyperparams: form.value.hyperparams,
    train_split: form.value.trainPct / 100,
    scaler: form.value.scaler === 'None' ? null : form.value.scaler.toLowerCase(),
    split_by: form.value.splitBy.toLowerCase(),
    max_segments: form.value.maxSeg,
    search_config: form.value.cvSearch.mode !== 'None' ? {
      mode: form.value.cvSearch.mode === 'Grid' ? 'grid' : 'random',
      folds: form.value.cvSearch.folds, nIter: form.value.cvSearch.nIter,
      scoring: form.value.cvSearch.scoring, paramGrid: form.value.paramGrid
    } : null
  }
  try {
    if (editing.value === 'new') {
      const { data } = await modelConfigsAPI.create(body)
      configs.value = [data, ...configs.value]
      toast.add({ severity: 'success', summary: 'Created', detail: data.name, life: 2500 })
    } else {
      const { data } = await modelConfigsAPI.update(editing.value, body)
      configs.value = configs.value.map((c) => (c.id === editing.value ? { ...c, ...data } : c))
      toast.add({ severity: 'success', summary: 'Saved', detail: data.name, life: 2500 })
    }
    editing.value = null
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Save failed', detail: e?.response?.data?.error ?? e.message, life: 4500 })
  } finally {
    saving.value = false
  }
}

const onDuplicate = async (cfg) => {
  try {
    const body = {
      name: `${cfg.name}_copy`, algorithm: cfg.algorithm,
      hyperparams: cfg.hyperparams_json ? JSON.parse(cfg.hyperparams_json) : {},
      train_split: cfg.train_split, scaler: cfg.scaler,
      split_by: cfg.split_by, max_segments: cfg.max_segments,
      search_config: cfg.search_config_json ? JSON.parse(cfg.search_config_json) : null
    }
    const { data } = await modelConfigsAPI.create(body)
    configs.value = [data, ...configs.value]
    toast.add({ severity: 'info', summary: 'Duplicated', detail: data.name, life: 2000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Duplicate failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}

const onDelete = (cfg) => {
  confirm.require({
    message: `Delete configuration "${cfg.name}"? This cannot be undone.`,
    header: 'Delete configuration',
    icon: 'pi pi-exclamation-triangle',
    acceptClass: 'p-button-danger',
    acceptLabel: 'Delete',
    accept: async () => {
      try {
        await modelConfigsAPI.delete(cfg.id)
        configs.value = configs.value.filter((c) => c.id !== cfg.id)
        toast.add({ severity: 'success', summary: 'Deleted', detail: cfg.name, life: 2000 })
      } catch (e) {
        const detail = e?.response?.data?.message ?? e?.response?.data?.error ?? e.message
        toast.add({ severity: 'error', summary: 'Cannot delete', detail, life: 5000 })
      }
    }
  })
}
</script>

<template>
  <div>
    <PageHeader eyebrow="MODEL" title="Model Configurations" subtitle="Save reusable configurations — apply them in New Model or per-sector overrides">
      <template #actions>
        <Button class="btn-new-cfg" icon="pi pi-plus" label="New Configuration" @click="openCreate()" />
      </template>
    </PageHeader>

    <div class="configs-grid">
      <!-- Algorithm sidebar -->
      <div class="panel algo-sidebar">
        <div class="eyebrow algo-sidebar-label">Algorithms</div>
        <div class="algo-row" :class="{ 'is-active': algoFilter === 'All' }" @click="algoFilter = 'All'">
          <span class="algo-row-name">All configurations</span>
          <span class="font-mono algo-row-count">{{ configs.length }}</span>
        </div>
        <template v-for="fam in algoTree" :key="fam.label">
          <div class="algo-fam-label">{{ fam.label }}</div>
          <div
            v-for="a in fam.algos" :key="a.name"
            class="algo-row algo-row--algo" :class="{ 'is-active': algoFilter === a.name }"
            @click="algoFilter = a.name"
          >
            <span class="font-mono algo-row-name">{{ a.name }}</span>
            <span v-if="a.count > 0" class="algo-count-badge font-mono">{{ a.count }}</span>
          </div>
        </template>
      </div>

      <div class="configs-main">
        <!-- Editor -->
        <div v-if="editorOpen" class="card-editor">
          <div class="eyebrow editor-title">{{ editorTitle }}</div>
          <div class="field-grid-2 mb-4">
            <div class="field-col">
              <label class="field-label">Name</label>
              <InputText v-model="form.name" placeholder="e.g. lasso_conservative" class="w-full font-mono" />
            </div>
            <div class="field-col">
              <label class="field-label">Algorithm</label>
              <EySelect v-model="form.algorithm" :options="registry" optionLabel="algorithm" optionValue="algorithm" placeholder="Select algorithm" class="w-full" />
            </div>
          </div>

          <div v-if="selectedAlgoMeta" class="field-col mb-4">
            <label class="field-label">Hyperparameters</label>
            <div class="hp-grid-3">
              <div v-for="p in selectedAlgoMeta.params" :key="p.name" class="hp-field">
                <span class="font-mono hp-name">{{ p.name }}</span>
                <InputText v-if="p.type === 'string'" v-model="form.hyperparams[p.name]" class="w-full font-mono" />
                <InputNumber
                  v-else-if="p.type === 'float' || p.type === 'int'"
                  v-model="form.hyperparams[p.name]"
                  :useGrouping="false" :minFractionDigits="p.type === 'float' ? 1 : 0" :maxFractionDigits="p.type === 'float' ? 6 : 0"
                  class="w-full font-mono" fluid
                />
                <InputSwitch v-else-if="p.type === 'bool'" v-model="form.hyperparams[p.name]" />
              </div>
            </div>
          </div>

          <div class="editor-divider" />
          <div class="eyebrow editor-section-label">Segmentation</div>
          <div class="field-grid-2 mb-4">
            <div class="field-col">
              <label class="field-label">Split by</label>
              <div class="seg-pill-group">
                <button type="button" class="seg-pill" :class="{ 'is-active': form.splitBy === 'Subsector' }" @click="form.splitBy = 'Subsector'">Subsector</button>
                <button type="button" class="seg-pill" :class="{ 'is-active': form.splitBy === 'Country' }" @click="form.splitBy = 'Country'">Country</button>
              </div>
            </div>
            <div class="field-col">
              <label class="field-label">Max segments per sector</label>
              <div class="seg-stepper">
                <button type="button" class="seg-stepper-btn" aria-label="Decrease max segments" @click="form.maxSeg = Math.max(2, form.maxSeg - 1)">−</button>
                <div class="seg-stepper-val font-mono">{{ form.maxSeg }}</div>
                <button type="button" class="seg-stepper-btn" aria-label="Increase max segments" @click="form.maxSeg = Math.min(20, form.maxSeg + 1)">+</button>
              </div>
            </div>
          </div>

          <Accordion :multiple="true" :activeIndex="[]" class="editor-accordion mb-4">
            <AccordionTab header="Training &amp; validation">
              <div class="field-grid-2">
                <div class="field-col">
                  <SplitSlider v-model="form.trainPct" />
                </div>
                <div class="field-col">
                  <label class="field-label">Feature scaler</label>
                  <div class="seg-pill-group">
                    <button v-for="o in SCALER_OPTIONS" :key="o" type="button" class="seg-pill" :class="{ 'is-active': form.scaler === o }" @click="form.scaler = o">{{ o }}</button>
                  </div>
                </div>
              </div>
            </AccordionTab>

            <AccordionTab header="Hyperparameter search">
              <div class="seg-pill-group mb-3">
                <button v-for="o in SEARCH_MODES" :key="o" type="button" class="seg-pill" :class="{ 'is-active': form.cvSearch.mode === o }" @click="form.cvSearch.mode = o">{{ o }}</button>
              </div>
              <template v-if="form.cvSearch.mode !== 'None' && selectedAlgoMeta">
                <div class="field-grid-3 mb-3">
                  <div class="field-col">
                    <label class="field-label">CV folds</label>
                    <InputNumber v-model="form.cvSearch.folds" :min="2" :max="20" :useGrouping="false" class="w-full" />
                  </div>
                  <div v-if="form.cvSearch.mode === 'Randomized'" class="field-col">
                    <label class="field-label">n_iter</label>
                    <InputNumber v-model="form.cvSearch.nIter" :min="1" :max="500" :useGrouping="false" class="w-full" />
                  </div>
                  <div class="field-col">
                    <label class="field-label">Scoring</label>
                    <EySelect v-model="form.cvSearch.scoring" :options="SCORING_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
                  </div>
                </div>
                <div class="grid-caption mb-2">{{ enabledParamCount }} of {{ selectedAlgoMeta.params.length }} enabled · {{ combinationCount.toLocaleString() }} combos</div>
                <div class="grid-table-scroll">
                  <table class="grid-table">
                    <thead>
                      <tr><th style="width:2rem"></th><th>Parameter</th><th style="width:6rem">Mode</th><th>Range / values</th><th style="width:4rem" class="ta-right">#</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="p in selectedAlgoMeta.params" :key="p.name" :class="{ 'is-disabled-row': !form.paramGrid[p.name]?.enabled }">
                        <td><Checkbox v-if="form.paramGrid[p.name]" v-model="form.paramGrid[p.name].enabled" :binary="true" /></td>
                        <td><span class="font-mono">{{ p.name }}</span></td>
                        <td>
                          <EySelect
                            v-if="form.paramGrid[p.name] && (p.type === 'float' || p.type === 'int')"
                            v-model="form.paramGrid[p.name].kind" :options="[{label:'Linear',value:'linspace'},{label:'Log',value:'logspace'},{label:'Values',value:'list'}]"
                            optionLabel="label" optionValue="value" :disabled="!form.paramGrid[p.name]?.enabled" class="w-full"
                          />
                          <span v-else class="tag-outline">values</span>
                        </td>
                        <td>
                          <div v-if="form.paramGrid[p.name] && (p.type === 'float' || p.type === 'int') && form.paramGrid[p.name].kind !== 'list'" class="range-row">
                            <InputNumber v-model="form.paramGrid[p.name].min" :disabled="!form.paramGrid[p.name]?.enabled" :useGrouping="false" :maxFractionDigits="6" placeholder="min" class="range-input" />
                            <span>&rarr;</span>
                            <InputNumber v-model="form.paramGrid[p.name].max" :disabled="!form.paramGrid[p.name]?.enabled" :useGrouping="false" :maxFractionDigits="6" placeholder="max" class="range-input" />
                            <span class="grid-caption">in</span>
                            <InputNumber v-model="form.paramGrid[p.name].steps" :disabled="!form.paramGrid[p.name]?.enabled" :min="2" :max="50" :useGrouping="false" class="step-input" />
                            <span class="grid-caption">steps</span>
                          </div>
                          <InputText v-else-if="form.paramGrid[p.name]" v-model="form.paramGrid[p.name].values" :disabled="!form.paramGrid[p.name]?.enabled" placeholder="comma-separated" class="w-full" />
                        </td>
                        <td class="ta-right font-mono grid-caption">{{ form.paramGrid[p.name]?.enabled ? expandValues(form.paramGrid[p.name]).length : '—' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
              <div v-else class="grid-caption">No search — the hyperparameter values above are used as-is.</div>
            </AccordionTab>
          </Accordion>

          <div class="editor-footer">
            <span class="grid-caption">Saved as a reusable configuration — apply it in New Model or per-sector overrides</span>
            <div class="footer-spacer" />
            <Button label="Cancel" outlined @click="cancelEdit" />
            <Button class="btn-cta" :loading="saving" @click="saveConfig">Save configuration</Button>
          </div>
        </div>

        <!-- Configs table -->
        <div class="panel configs-panel">
          <div class="configs-header">
            <h3>{{ algoFilter === 'All' ? 'All configurations' : algoFilter }}</h3>
            <span class="configs-count">{{ filteredConfigs.length }} configuration{{ filteredConfigs.length !== 1 ? 's' : '' }}</span>
            <div class="spacer" />
            <InputText v-model="search" placeholder="Search configurations…" class="configs-search" />
          </div>

          <BaseTable :columns="CONFIG_COLS" :value="filteredConfigs" dataKey="id" :bleed="16">
            <template #empty>
              <div v-if="!loading" class="empty-state">
                <div class="empty-title">No configurations for this algorithm</div>
                <div class="empty-sub">Create one with <strong>+ New Configuration</strong></div>
              </div>
            </template>

            <template #cell-name="{ row }">
              <span class="cfg-name">{{ row.name }}</span>
            </template>
            <template #cell-algorithm="{ row }">
              <span class="font-mono cfg-algo">{{ row.algorithm }}</span>
            </template>
            <template #cell-settings="{ row }">
              <span class="font-mono cfg-settings">{{ settingsSummary(row) }}</span>
            </template>
            <template #cell-used_by="{ row }">
              <span class="font-mono cfg-usedby">{{ row.used_by }}</span>
            </template>
            <template #cell-updated="{ row }">
              <span class="font-mono cfg-updated">{{ fmtDate(row.created_at) }}</span>
            </template>
            <template #cell-actions="{ row }">
              <div class="cfg-actions">
                <span class="action-link" @click="openEdit(row)">Edit</span>
                <span class="action-link" @click="onDuplicate(row)">Duplicate</span>
                <span class="action-link action-link--danger" @click="onDelete(row)">Delete</span>
              </div>
            </template>
          </BaseTable>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.btn-new-cfg { height: 38px; padding: 0 18px; }

.configs-grid { display: grid; grid-template-columns: 280px 1fr; gap: 20px; align-items: start; }
.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; }

.algo-sidebar { padding: 12px 0 10px; }
.algo-sidebar-label { padding: 0 16px 8px; }
.algo-fam-label { padding: 12px 16px 5px; font-size: 10.5px; font-weight: 700; letter-spacing: 0.09em; color: var(--text-color-muted-2); }
.algo-row {
  display: flex; align-items: center; gap: 8px; height: 34px; padding: 0 16px 0 13px;
  cursor: pointer; font-size: 13px; border-left: 3px solid transparent; color: var(--text-color-secondary);
}
.algo-row:hover { background: var(--surface-hover); }
.algo-row.is-active { border-left-color: var(--yellow); background: var(--surface-ground); color: var(--text-color); font-weight: 600; }
.algo-row-name { flex: 1; }
.algo-row-count { color: var(--text-color-muted-2); font-size: 11px; }
.algo-row--algo { font-size: 12.5px; }
.algo-count-badge { background: var(--ink); color: var(--yellow); font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 2px; }

/* min-width:0 lets this grid column shrink instead of letting wide editor
   content (hyperparameter grid, search table) overflow and push the page
   wider than the viewport — which is what misaligned the header button. */
.configs-main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }

.card-editor { background: var(--surface-card); border: 1px solid var(--surface-border); border-top: 3px solid var(--yellow); border-radius: 2px; padding: 20px 24px; }
.editor-title { margin-bottom: 14px; }
/* Hairline section dividers group the editor into basics · segmentation. */
.editor-divider { height: 1px; background: var(--surface-border); margin: 4px 0 16px; }
.editor-section-label { margin-bottom: 14px; }

/* Max-segments stepper (mockup) — bordered −/value/+ with yellow hover. */
.seg-stepper { display: inline-flex; align-self: flex-start; align-items: stretch; border: 1px solid var(--surface-border-input); border-radius: 2px; overflow: hidden; }
.seg-stepper-btn { width: 38px; height: 38px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 16px; color: var(--text-color-secondary); background: #fff; border: none; }
.seg-stepper-btn:first-child { border-right: 1px solid var(--surface-border-row); }
.seg-stepper-btn:last-child { border-left: 1px solid var(--surface-border-row); }
.seg-stepper-btn:hover { background: var(--yellow); color: var(--ink); }
.seg-stepper-btn:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--yellow); }
.seg-stepper-val { width: 56px; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 600; height: 38px; }

/* Collapsible editor sections. Flat, ink headers matching the section eyebrows. */
.grid-table-scroll { overflow-x: auto; }
:deep(.editor-accordion .p-accordion-tab) { margin-bottom: 10px; }
:deep(.editor-accordion .p-accordion-header-link) {
  background: var(--surface-inset);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 12px 14px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-color);
}
:deep(.editor-accordion .p-accordion-header:not(.p-disabled).p-highlight .p-accordion-header-link) {
  border-color: var(--ink);
}
:deep(.editor-accordion .p-accordion-header-link:focus) { box-shadow: 0 0 0 2px var(--yellow); }
:deep(.editor-accordion .p-accordion-content) {
  border: 1px solid var(--surface-border);
  border-top: 0;
  padding: 16px 14px;
}

@media (max-width: 720px) {
  .field-grid-2, .field-grid-3, .hp-grid-3 { grid-template-columns: 1fr; }
}
.editor-footer { display: flex; align-items: center; gap: 12px; }
.footer-spacer { flex: 1; }

.field-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.field-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.field-col { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); }
.mb-4 { margin-bottom: 16px; }
.mb-3 { margin-bottom: 12px; }
.mb-2 { margin-bottom: 8px; }

.hp-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.hp-field { display: flex; flex-direction: column; gap: 5px; }
.hp-name { font-size: 11.5px; color: var(--text-color-secondary); }

.advanced-panel { background: var(--surface-inset); border-radius: 2px; padding: 16px 18px; }
.grid-caption { font-size: 11.5px; color: var(--text-color-muted); }
.grid-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.grid-table th { text-align: left; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-color-muted); padding: 6px 8px; border-bottom: 2px solid var(--ink); }
.grid-table td { padding: 6px 8px; border-bottom: 1px solid var(--surface-border-row); vertical-align: middle; }
.grid-table tr.is-disabled-row { opacity: 0.55; }
.ta-right { text-align: right; }
.range-row { display: flex; align-items: center; gap: 8px; }
:deep(.range-input) { width: 6rem; }
:deep(.step-input) { width: 3.5rem; }

.tag-outline { display: inline-flex; align-items: center; border: 1px solid var(--surface-border-input); color: var(--text-color-secondary); font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 7px; border-radius: 2px; }

.seg-pill-group { display: inline-flex; align-self: flex-start; width: fit-content; border: 1px solid var(--ink); border-radius: 2px; overflow: hidden; }
.seg-pill { padding: 9px 16px; border: 0; background: #FFFFFF; color: var(--text-color-secondary); font-size: 13px; font-weight: 600; cursor: pointer; }
.seg-pill.is-active { background: var(--ink); color: var(--yellow); }

.configs-panel { padding: 0 16px 4px; }
.configs-header { display: flex; align-items: center; gap: 12px; padding: 14px 0; }
.configs-header h3 { flex: none; }
.configs-count { font-size: 12px; color: var(--text-color-muted); }
.spacer { flex: 1; }
.configs-search { width: 220px; height: 34px; }

.cfg-name { font-size: 13.5px; font-weight: 600; }
.cfg-algo { font-size: 12px; color: var(--text-color-secondary); }
.cfg-settings { display: block; max-width: 340px; font-size: 11px; color: var(--text-color-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cfg-usedby { font-size: 12px; color: var(--text-color-secondary); }
.cfg-updated { font-size: 11.5px; color: var(--text-color-secondary); }
.cfg-actions { display: flex; gap: 12px; justify-content: flex-end; }
.action-link { font-size: 12px; font-weight: 600; color: var(--text-color-secondary); cursor: pointer; border-bottom: 2px solid transparent; }
.action-link:hover { border-bottom-color: var(--yellow); color: var(--text-color); }
.action-link--danger { color: var(--text-color-muted-2); }
.action-link--danger:hover { border-bottom-color: var(--error-color); color: var(--error-text-color); }

.empty-state { text-align: center; padding: 28px 16px; }
.empty-title { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.empty-sub { font-size: 12.5px; color: var(--text-color-muted); }

@media (max-width: 900px) {
  .configs-grid { grid-template-columns: 1fr; }
}
</style>
