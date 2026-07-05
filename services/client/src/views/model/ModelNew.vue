<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import PageHeader from '@/components/ui/PageHeader.vue'
import {
  mode, datasets, selectedDatasetId, targetCol, selectedSectors, availableSectors, loadingSectors,
  configs, selectedConfigId, featureCols, sectorOverrides, modelName,
  selectedDataset, columnOptions, featureOptions, selectedConfig, objectiveLabel,
  fetchDatasets, fetchConfigs, fetchSectors, resetNewModelForm
} from './newModelStore'

const router = useRouter()
const toast = useToast()

// ── Auto mode — frontend-only until the backend orchestration exists ────────
const optimizationMetric = ref('rmse')
const OPTIMIZATION_OPTIONS = [
  { label: 'RMSE', value: 'rmse' },
  { label: 'R²', value: 'r2' },
  { label: 'MAE', value: 'mae' }
]
const trainingBudget = ref('1h')
const BUDGET_OPTIONS = [
  { label: '15 minutes', value: '15m' },
  { label: '30 minutes', value: '30m' },
  { label: '1 hour', value: '1h' },
  { label: '2 hours', value: '2h' }
]
const AUTO_CANDIDATES = ['ElasticNet', 'Ridge', 'GradientBoosting', 'RandomForest']

watch(selectedDatasetId, (id) => {
  targetCol.value = null
  selectedSectors.value = []
  sectorOverrides.value = {}
  fetchSectors(id)
})
watch(targetCol, () => { featureCols.value = [...featureOptions.value] })
watch(selectedSectors, (sectors, prev) => {
  const removed = (prev || []).filter((s) => !sectors.includes(s))
  if (removed.length) {
    const next = { ...sectorOverrides.value }
    removed.forEach((s) => delete next[s])
    sectorOverrides.value = next
  }
})

const featsTriggerLabel = computed(() =>
  featureCols.value.length === featureOptions.value.length
    ? `All features (${featureOptions.value.length})`
    : `${featureCols.value.length} of ${featureOptions.value.length} features selected`
)
const sectorsTriggerLabel = computed(() =>
  selectedSectors.value.length === availableSectors.value.length && availableSectors.value.length > 0
    ? `All sectors (${availableSectors.value.length})`
    : selectedSectors.value.length
      ? `${selectedSectors.value.length} of ${availableSectors.value.length} sectors selected`
      : 'No segmentation — single model'
)

// ── Per-sector override rows ─────────────────────────────────────────────────
const customizingSector = ref(null)
const overrideDraft = ref({}) // { model_config_id, feature_cols }

const perSectorRows = computed(() =>
  selectedSectors.value.map((name) => {
    const isCustom = !!sectorOverrides.value[name]
    const panelOpen = customizingSector.value === name
    const ov = sectorOverrides.value[name]
    const cfgName = isCustom ? (configs.value.find((c) => c.id === ov.model_config_id)?.name ?? '—') : null
    const featSummary = isCustom
      ? (ov.feature_cols.length === featureOptions.value.length ? 'all features' : `${ov.feature_cols.length} features`)
      : null
    return {
      name, isCustom, panelOpen,
      tag: isCustom ? 'CUSTOMIZED' : 'DEFAULT',
      summary: isCustom
        ? `${cfgName} · ${featSummary}`
        : `${selectedConfig.value?.name ?? '—'} · ${featureCols.value.length === featureOptions.value.length ? 'all' : featureCols.value.length} features`,
      actionLabel: panelOpen ? 'Close' : (isCustom ? 'Edit' : 'Customize')
    }
  })
)

const toggleCustomize = (sector) => {
  if (customizingSector.value === sector) { customizingSector.value = null; return }
  customizingSector.value = sector
  const existing = sectorOverrides.value[sector]
  overrideDraft.value = {
    model_config_id: existing?.model_config_id ?? selectedConfigId.value,
    feature_cols: existing ? [...existing.feature_cols] : [...featureCols.value]
  }
}
const cancelOverride = () => { customizingSector.value = null }
const applyOverride = (sector) => {
  sectorOverrides.value = { ...sectorOverrides.value, [sector]: { ...overrideDraft.value } }
  customizingSector.value = null
}
const resetOverride = (sector) => {
  const next = { ...sectorOverrides.value }
  delete next[sector]
  sectorOverrides.value = next
}
const overrideFeatureOptions = computed(() => featureOptions.value)
const overrideFeatsLabel = computed(() =>
  (overrideDraft.value.feature_cols?.length ?? 0) === overrideFeatureOptions.value.length
    ? `All features (${overrideFeatureOptions.value.length})`
    : `${overrideDraft.value.feature_cols?.length ?? 0} of ${overrideFeatureOptions.value.length} features`
)

// ── Review & submit ───────────────────────────────────────────────────────────
const summaryRows = computed(() => [
  { k: 'Mode', v: mode.value === 'auto' ? 'Auto' : 'Manual' },
  { k: 'Algorithm', v: mode.value === 'auto' ? 'Auto-selected' : (selectedConfig.value ? `${selectedConfig.value.name} · ${selectedConfig.value.algorithm}` : '—') },
  { k: 'Dataset', v: selectedDataset.value?.name ?? '—' },
  { k: 'Target', v: targetCol.value ?? '—' },
  { k: 'Sectors', v: selectedSectors.value.length ? `${selectedSectors.value.length} of ${availableSectors.value.length}` : 'None' },
  { k: 'Segments', v: mode.value === 'auto' ? 'Automatic' : (selectedConfig.value ? `${selectedConfig.value.split_by} ≤${selectedConfig.value.max_segments}` : '—') }
])

const submitting = ref(false)
const canLaunch = computed(() =>
  mode.value === 'manual' &&
  !!selectedDatasetId.value &&
  !!targetCol.value &&
  !!selectedConfigId.value &&
  !!modelName.value.trim()
)

const launch = async () => {
  if (mode.value === 'auto') {
    toast.add({ severity: 'warn', summary: 'Auto training unavailable', detail: 'Auto mode is not wired up to the backend yet — switch to Manual to launch a run.', life: 4500 })
    return
  }
  if (!canLaunch.value) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Fill in the model name, dataset, target column and a model configuration.', life: 3500 })
    return
  }
  submitting.value = true
  try {
    const cfg = selectedConfig.value
    const sectorOverridesPayload = {}
    for (const [sector, ov] of Object.entries(sectorOverrides.value)) {
      const ovCfg = configs.value.find((c) => c.id === ov.model_config_id)
      sectorOverridesPayload[sector] = {
        model_config_id: ov.model_config_id,
        feature_cols: ov.feature_cols,
        split_by: ovCfg?.split_by ?? cfg.split_by,
        max_segments: ovCfg?.max_segments ?? cfg.max_segments
      }
    }
    const payload = {
      dataset_id: selectedDatasetId.value,
      model_config_id: cfg.id,
      target_col: targetCol.value,
      feature_cols: featureCols.value,
      segmentation: selectedSectors.value.length > 0
        ? {
            sectors: selectedSectors.value,
            split_by: cfg.split_by,
            max_segments: cfg.max_segments,
            ...(Object.keys(sectorOverridesPayload).length ? { sector_overrides: sectorOverridesPayload } : {})
          }
        : null
    }
    const { data } = await calibrationsAPI.create(payload)
    toast.add({ severity: 'success', summary: 'Training queued', detail: `Run ${data.run_id}`, life: 3000 })
    resetNewModelForm()
    router.push({ name: 'jobs_detail', params: { kind: 'training', run_id: data.run_id } })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Launch failed', detail: e?.response?.data?.error ?? e.message, life: 4500 })
  } finally {
    submitting.value = false
  }
}

let loaded = false
onMounted(async () => {
  if (loaded) return
  loaded = true
  try {
    await Promise.all([fetchDatasets(), fetchConfigs()])
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
})
onUnmounted(() => { loaded = false })
</script>

<template>
  <div class="model-new">
    <PageHeader eyebrow="MODEL" title="New Model" subtitle="Build and train a segmented model in one flow" />

    <!-- Mode picker -->
    <div class="mode-grid">
      <button type="button" class="mode-card" :class="{ 'is-active': mode === 'auto' }" @click="mode = 'auto'">
        <div class="mode-head">
          <span class="radio-dot" :class="{ 'is-checked': mode === 'auto' }" />
          <span class="mode-title">Auto</span>
          <span class="tag-fill mode-badge">RECOMMENDED</span>
        </div>
        <p class="mode-desc">CREST selects algorithms, tunes hyperparameters and segments automatically. Best for experimentation and high-level work.</p>
      </button>
      <button type="button" class="mode-card" :class="{ 'is-active': mode === 'manual' }" @click="mode = 'manual'">
        <div class="mode-head">
          <span class="radio-dot" :class="{ 'is-checked': mode === 'manual' }" />
          <span class="mode-title">Manual</span>
        </div>
        <p class="mode-desc">Full control over algorithm, hyperparameters, segmentation and features. Built for technical users.</p>
      </button>
    </div>

    <!-- 01 Dataset -->
    <div class="step-card card--emphasis">
      <div class="step-head">
        <span class="step-badge font-mono">01</span>
        <span class="step-title">Dataset</span>
      </div>
      <Dropdown
        v-model="selectedDatasetId" :options="datasets" optionLabel="name" optionValue="id"
        placeholder="Select dataset" class="w-full" filter
      />
      <div v-if="selectedDataset" class="inset-strip">
        <div class="inset-field"><span class="inset-label">Rows</span><span class="font-mono inset-value">{{ selectedDataset.row_count.toLocaleString() }}</span></div>
        <div class="inset-field"><span class="inset-label">Columns</span><span class="font-mono inset-value">{{ selectedDataset.columns.length }}</span></div>
        <div class="inset-field"><span class="inset-label">Type</span><span class="font-mono inset-value">Calibration</span></div>
      </div>
    </div>

    <!-- 02 Target -->
    <div class="step-card card--emphasis">
      <div class="step-head">
        <span class="step-badge font-mono">02</span>
        <span class="step-title">Target</span>
      </div>
      <div class="field-label">Target column</div>
      <Dropdown
        v-model="targetCol" :options="columnOptions" placeholder="Select target column"
        :disabled="columnOptions.length === 0" class="w-full font-mono mb-3" filter
      />
      <div v-if="objectiveLabel" class="inset-strip inset-strip--tag">
        <span class="tag-fill">{{ objectiveLabel.toUpperCase() }}</span>
        <span class="inset-note">Objective detected automatically from the target column type</span>
      </div>

      <div class="field-label mt-4">Sectors to model</div>
      <div v-if="loadingSectors" class="grid-caption"><i class="pi pi-spin pi-spinner" /> Loading sectors…</div>
      <MultiSelect
        v-else
        v-model="selectedSectors" :options="availableSectors"
        :disabled="!selectedDatasetId || availableSectors.length === 0"
        display="chip" :showToggleAll="true" class="w-full"
        :placeholder="sectorsTriggerLabel" filter
      />
      <div class="grid-caption mt-2">A separate segmented model is trained for each selected sector</div>
    </div>

    <!-- 03 Model configuration -->
    <div class="step-card card--emphasis">
      <div class="step-head">
        <span class="step-badge font-mono">03</span>
        <span class="step-title">Model configuration</span>
        <span class="tag-outline step-mode-tag">{{ mode.toUpperCase() }}</span>
      </div>

      <!-- Auto -->
      <template v-if="mode === 'auto'">
        <div class="auto-info-panel">
          <p class="m-0">
            CREST will fit
            <span v-for="(a, i) in AUTO_CANDIDATES" :key="a" class="font-mono">{{ a }}<template v-if="i < AUTO_CANDIDATES.length - 1">, </template></span>
            as candidates and keep the model with the best validation score. Segmentation is decided automatically from
            dataset composition.
          </p>
        </div>
        <div class="field-grid-2">
          <div class="field-col">
            <label class="field-label">Optimization metric</label>
            <Dropdown v-model="optimizationMetric" :options="OPTIMIZATION_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
          </div>
          <div class="field-col">
            <label class="field-label">Training budget</label>
            <Dropdown v-model="trainingBudget" :options="BUDGET_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
          </div>
        </div>
      </template>

      <!-- Manual -->
      <template v-else>
        <div class="field-row-baseline mb-2">
          <label class="field-label">Model configuration</label>
          <div class="spacer" />
          <span class="text-link" @click="router.push({ name: 'model_configurations' })">Manage configurations &rarr;</span>
        </div>
        <Dropdown v-model="selectedConfigId" :options="configs" optionValue="id" placeholder="Select a configuration" class="w-full mb-3" filter>
          <template #value="{ value }">
            <span v-if="selectedConfig" class="cfg-value">
              <span class="font-mono">{{ selectedConfig.name }}</span>
              <span class="tag-fill cfg-algo-tag">{{ selectedConfig.algorithm }}</span>
            </span>
            <span v-else class="p-placeholder">Select a configuration</span>
          </template>
          <template #option="{ option }">
            <span class="cfg-option">
              <span class="font-mono cfg-option-name">{{ option.name }}</span>
              <span class="tag-outline">{{ option.algorithm }}</span>
            </span>
          </template>
        </Dropdown>
        <div v-if="configs.length === 0" class="grid-caption mb-3">No configurations saved yet — <span class="text-link" @click="router.push({ name: 'model_configurations' })">create one</span>.</div>

        <div v-if="selectedConfig" class="inset-strip mb-4">
          <div class="inset-field"><span class="inset-label">Split</span><span class="font-mono inset-value">{{ Math.round((selectedConfig.train_split ?? 0.8) * 100) }}/{{ 100 - Math.round((selectedConfig.train_split ?? 0.8) * 100) }}</span></div>
          <div class="inset-field"><span class="inset-label">Segmentation</span><span class="font-mono inset-value">{{ selectedConfig.split_by }} &le;{{ selectedConfig.max_segments }}</span></div>
          <div class="inset-field"><span class="inset-label">Scaler</span><span class="font-mono inset-value">{{ selectedConfig.scaler || 'None' }}</span></div>
          <div class="inset-field"><span class="inset-label">Search</span><span class="font-mono inset-value">{{ selectedConfig.search_config_json ? (JSON.parse(selectedConfig.search_config_json).mode === 'random' ? 'Randomized' : 'Grid') : 'Off' }}</span></div>
        </div>

        <div class="field-row-baseline mb-2">
          <label class="field-label">Feature columns</label>
          <div class="spacer" />
          <span class="text-link" @click="router.push({ name: 'model_feature_selection' })">Advanced feature selection &rarr;</span>
        </div>
        <MultiSelect
          v-model="featureCols" :options="featureOptions" :disabled="!targetCol"
          display="chip" :showToggleAll="true" class="w-full font-mono"
          :placeholder="featsTriggerLabel" filter
        />
        <div class="grid-caption mt-2 mb-4">All non-target columns are used by default</div>

        <div class="divider" />
        <div class="field-row-baseline mb-3">
          <label class="field-label">Per-sector configuration</label>
          <span class="grid-caption">The configuration above applies to all sectors — customize a sector to override it</span>
        </div>
        <div v-for="row in perSectorRows" :key="row.name" class="ps-row">
          <div class="ps-name">{{ row.name }}</div>
          <span class="tag-outline" :class="{ 'tag-outline--custom': row.isCustom }">{{ row.tag }}</span>
          <div class="font-mono ps-summary">{{ row.summary }}</div>
          <span v-if="row.isCustom" class="text-link text-link--danger" @click="resetOverride(row.name)">Reset</span>
          <span class="text-link" @click="toggleCustomize(row.name)">{{ row.actionLabel }}</span>
        </div>
        <div v-if="customizingSector" class="ps-override-panel">
          <div class="field-row-baseline mb-3">
            <span class="eyebrow">OVERRIDE — <span class="font-mono">{{ customizingSector }}</span></span>
            <div class="spacer" />
            <span class="text-link" @click="router.push({ name: 'model_configurations' })">Manage configurations &rarr;</span>
          </div>
          <div class="field-grid-2 mb-3">
            <div class="field-col">
              <label class="field-label">Configuration</label>
              <Dropdown v-model="overrideDraft.model_config_id" :options="configs" optionValue="id" class="w-full" filter>
                <template #value="{ value }">
                  <span v-if="configs.find(c => c.id === value)" class="cfg-value">
                    <span class="font-mono">{{ configs.find(c => c.id === value).name }}</span>
                    <span class="tag-outline">{{ configs.find(c => c.id === value).algorithm }}</span>
                  </span>
                </template>
                <template #option="{ option }">
                  <span class="cfg-option">
                    <span class="font-mono cfg-option-name">{{ option.name }}</span>
                    <span class="tag-outline">{{ option.algorithm }}</span>
                  </span>
                </template>
              </Dropdown>
            </div>
            <div class="field-col">
              <label class="field-label">Feature columns</label>
              <MultiSelect v-model="overrideDraft.feature_cols" :options="overrideFeatureOptions" display="chip" :showToggleAll="true" class="w-full font-mono" :placeholder="overrideFeatsLabel" filter />
            </div>
          </div>
          <div class="ps-override-footer">
            <span class="grid-caption">Overrides the configuration and feature columns for this sector only — segmentation, split, scaler and hyperparameters come from the chosen configuration</span>
            <div class="spacer" />
            <Button label="Cancel" outlined size="small" @click="cancelOverride" />
            <Button class="btn-cta" size="small" @click="applyOverride(customizingSector)">Apply override</Button>
          </div>
        </div>
      </template>
    </div>

    <!-- 04 Review & train -->
    <div class="step-card card--emphasis">
      <div class="step-head">
        <span class="step-badge font-mono">04</span>
        <span class="step-title">Review &amp; train</span>
      </div>
      <div class="field-col mb-4">
        <label class="field-label">Model name</label>
        <InputText v-model="modelName" placeholder="e.g. std_q3_experiment" class="w-full" />
      </div>
      <div class="summary-strip">
        <div v-for="r in summaryRows" :key="r.k" class="summary-field">
          <span class="inset-label">{{ r.k }}</span>
          <span class="font-mono inset-value">{{ r.v }}</span>
        </div>
      </div>
    </div>

    <!-- Sticky footer -->
    <div class="footer-bar">
      <span v-if="mode === 'auto'" class="grid-caption footer-note">Auto training isn't available yet — switch to Manual to launch a run.</span>
      <div class="footer-spacer" />
      <Button label="Cancel" outlined @click="router.push({ name: 'jobs_history' })" />
      <Button class="btn-cta" :loading="submitting" :disabled="mode === 'manual' && (!canLaunch || submitting)" @click="launch">
        <span class="btn-play">&#9654;</span>
        <span>Start training</span>
      </Button>
    </div>
  </div>
</template>

<style scoped>
.model-new { max-width: 1040px; margin: 0 auto; padding-bottom: 32px; }

.mode-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 20px; }
.mode-card { text-align: left; background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; padding: 16px 18px; cursor: pointer; transition: border-color 0.15s ease; }
.mode-card:hover { border-color: var(--text-color-muted); }
.mode-card.is-active { border: 2px solid var(--ink); padding: 15px 17px; }
.mode-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.mode-title { font-size: 14.5px; font-weight: 700; }
.mode-badge { font-size: 9.5px; }
.mode-desc { font-size: 12.5px; color: var(--text-color-secondary); margin: 0; line-height: 1.5; }

.radio-dot { width: 20px; height: 20px; border-radius: 50%; border: 1px solid var(--surface-500); flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; }
.radio-dot.is-checked { border: 2px solid var(--ink); background: var(--yellow); }
.radio-dot.is-checked::after { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--ink); }

.tag-fill { display: inline-flex; align-items: center; background: var(--ink); color: var(--yellow); font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 7px; border-radius: 2px; }
.tag-outline { display: inline-flex; align-items: center; border: 1px solid var(--surface-border-input); color: var(--text-color-secondary); font-size: 9.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 7px; border-radius: 2px; }
.tag-outline--custom { background: var(--ink); color: var(--yellow); border-color: var(--ink); }

.step-card { padding: 20px 22px; margin-bottom: 16px; }
.step-head { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.step-badge { width: 26px; height: 26px; flex-shrink: 0; background: var(--ink); color: var(--yellow); border-radius: 2px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }
.step-title { font-size: 15px; font-weight: 700; flex: 1; }
.step-mode-tag { margin-left: auto; }

.inset-strip { display: flex; flex-wrap: wrap; gap: 22px; background: var(--surface-inset); border-radius: 2px; padding: 12px 16px; margin-top: 12px; }
.inset-strip--tag { align-items: center; gap: 10px; }
.inset-field { display: flex; flex-direction: column; gap: 2px; }
.inset-label { font-size: 10.5px; color: var(--text-color-muted); text-transform: uppercase; letter-spacing: 0.06em; }
.inset-value { font-size: 13px; font-weight: 600; }
.inset-note { font-size: 12px; color: var(--text-color-secondary); }

.auto-info-panel { border-left: 4px solid var(--yellow); background: var(--surface-inset); padding: 14px 16px; font-size: 13px; color: var(--text-color-secondary); line-height: 1.6; margin-bottom: 16px; border-radius: 0 2px 2px 0; }

.field-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.field-col { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-color-muted); margin-bottom: 8px; display: block; }
.field-row-baseline { display: flex; align-items: baseline; gap: 12px; }
.spacer { flex: 1; }
.mb-2 { margin-bottom: 8px; }
.mb-3 { margin-bottom: 12px; }
.mb-4 { margin-bottom: 16px; }
.mt-2 { margin-top: 6px; }
.mt-4 { margin-top: 18px; margin-bottom: 8px; }

.text-link { font-size: 12px; font-weight: 600; color: var(--text-color-secondary); cursor: pointer; border-bottom: 2px solid var(--yellow); padding-bottom: 1px; }
.text-link:hover { color: var(--text-color); }
.text-link--danger { border-bottom-color: transparent; color: var(--text-color-muted-2); }
.text-link--danger:hover { border-bottom-color: var(--error-color); color: var(--error-text-color); }

.grid-caption { font-size: 12px; color: var(--text-color-muted-2); }

.cfg-value, .cfg-option { display: flex; align-items: center; gap: 10px; }
.cfg-option-name { flex: 1; }
.cfg-algo-tag { font-family: 'Archivo', sans-serif; }

.divider { height: 1px; background: var(--surface-border-row); margin: 4px 0 16px; }

.ps-row { display: flex; align-items: center; gap: 12px; min-height: 44px; border-bottom: 1px solid var(--surface-border-row); padding: 4px 2px; }
.ps-name { width: 180px; flex: none; font-size: 13px; font-weight: 600; }
.ps-summary { flex: 1; font-size: 11.5px; color: var(--text-color-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.ps-override-panel { background: var(--surface-inset); border-radius: 2px; padding: 14px 16px; margin-top: 4px; }
.ps-override-footer { display: flex; align-items: center; gap: 12px; margin-top: 4px; }

.summary-strip { display: flex; flex-wrap: wrap; gap: 24px; background: var(--surface-inset); border-radius: 2px; padding: 14px 18px; }
.summary-field { display: flex; flex-direction: column; gap: 3px; }

.footer-bar { position: sticky; bottom: 0; display: flex; align-items: center; gap: 12px; background: var(--surface-card); border-top: 1px solid var(--surface-border); padding: 14px 4px; margin-top: 8px; }
.footer-spacer { flex: 1; }
.footer-note { color: var(--text-color-muted); }
.btn-play { color: var(--yellow); margin-right: 6px; }
</style>
