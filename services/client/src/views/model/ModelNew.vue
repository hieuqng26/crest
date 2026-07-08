<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import workflowsAPI from '@/api/workflowsAPI'
import PageHeader from '@/components/ui/PageHeader.vue'
import { fmtDate } from '@/utils/datetime'
import {
  mode, loadingDatasets, targetCols, selectedSectors, availableSectors, loadingSectors,
  configs, selectedConfigId, featureCols, targetOverrides, sectorOverrides, modelName, analysisParams,
  calibrationDataset, forecastDataset, creditDataset, financialDataset,
  targetColumnOptions, featureOptions, selectedConfig, objectiveFor,
  analysisReady, missingAnalysisTargets, analysisDatasetsReady,
  fetchResolvedDatasets, fetchConfigs, fetchSectors, resetNewModelForm
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

watch(calibrationDataset, (ds) => { if (ds) fetchSectors(ds.id) })
watch(targetCols, () => {
  featureCols.value = [...featureOptions.value]
  const next = {}
  for (const t of targetCols.value) if (targetOverrides.value[t]) next[t] = targetOverrides.value[t]
  targetOverrides.value = next
})
watch(selectedSectors, (sectors, prev) => {
  const removed = (prev || []).filter((s) => !sectors.includes(s))
  if (removed.length) {
    const next = { ...sectorOverrides.value }
    removed.forEach((s) => delete next[s])
    sectorOverrides.value = next
  }
})

const dataSourceRows = computed(() => [
  { key: 'calibration', label: 'Training dataset', ds: calibrationDataset.value, required: true },
  { key: 'forecast', label: 'Macro forecast dataset', ds: forecastDataset.value, required: true },
  { key: 'credit', label: 'Credit portfolio dataset', ds: creditDataset.value, required: false },
  { key: 'financial_portfolio', label: 'Financial portfolio dataset', ds: financialDataset.value, required: false }
])

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
const targetsTriggerLabel = computed(() =>
  targetCols.value.length ? `${targetCols.value.length} target${targetCols.value.length > 1 ? 's' : ''} selected` : 'Select target columns'
)

// ── Per-target override rows ─────────────────────────────────────────────────
const customizingTarget = ref(null)
const targetOverrideDraft = ref({}) // { model_config_id, feature_cols }

const perTargetRows = computed(() =>
  targetCols.value.map((name) => {
    const isCustom = !!targetOverrides.value[name]
    const panelOpen = customizingTarget.value === name
    const ov = targetOverrides.value[name]
    const cfgName = isCustom ? (configs.value.find((c) => c.id === ov.model_config_id)?.name ?? '—') : null
    const featSummary = isCustom
      ? (ov.feature_cols.length === featureOptions.value.length ? 'all features' : `${ov.feature_cols.length} features`)
      : null
    return {
      name,
      objective: objectiveFor(name),
      isCustom,
      panelOpen,
      tag: isCustom ? 'CUSTOMIZED' : 'DEFAULT',
      summary: isCustom
        ? `${cfgName} · ${featSummary}`
        : `${selectedConfig.value?.name ?? '—'} · ${featureCols.value.length === featureOptions.value.length ? 'all' : featureCols.value.length} features`,
      actionLabel: panelOpen ? 'Close' : (isCustom ? 'Edit' : 'Customize')
    }
  })
)

const toggleCustomizeTarget = (target) => {
  if (customizingTarget.value === target) { customizingTarget.value = null; return }
  customizingTarget.value = target
  const existing = targetOverrides.value[target]
  targetOverrideDraft.value = {
    model_config_id: existing?.model_config_id ?? selectedConfigId.value,
    feature_cols: existing ? [...existing.feature_cols] : [...featureCols.value]
  }
}
const cancelTargetOverride = () => { customizingTarget.value = null }
const applyTargetOverride = (target) => {
  targetOverrides.value = { ...targetOverrides.value, [target]: { ...targetOverrideDraft.value } }
  customizingTarget.value = null
}
const resetTargetOverride = (target) => {
  const next = { ...targetOverrides.value }
  delete next[target]
  targetOverrides.value = next
}
const targetOverrideFeatsLabel = computed(() =>
  (targetOverrideDraft.value.feature_cols?.length ?? 0) === featureOptions.value.length
    ? `All features (${featureOptions.value.length})`
    : `${targetOverrideDraft.value.feature_cols?.length ?? 0} of ${featureOptions.value.length} features`
)

// ── Per-sector override rows (applies within every target) ──────────────────
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

// ── Collapsible section state (both default collapsed — advanced/optional) ──
const showTargetOverrides = ref(false)
const showSectorOverrides = ref(false)
const targetOverrideCount = computed(() => Object.keys(targetOverrides.value).length)
const sectorOverrideCount = computed(() => Object.keys(sectorOverrides.value).length)
const toggleTargetSection = () => {
  showTargetOverrides.value = !showTargetOverrides.value
  if (!showTargetOverrides.value) customizingTarget.value = null
}
const toggleSectorSection = () => {
  showSectorOverrides.value = !showSectorOverrides.value
  if (!showSectorOverrides.value) customizingSector.value = null
}

// ── Review & submit ───────────────────────────────────────────────────────────
const analysisStageLabel = computed(() => {
  if (!creditDataset.value) return 'SKIPPED — no credit portfolio dataset uploaded'
  if (!analysisReady.value) return `SKIPPED — requires ${missingAnalysisTargets.value.join(', ')} among targets`
  return 'READY'
})
const analysisWillRun = computed(() => analysisReady.value && analysisDatasetsReady.value)

const summaryRows = computed(() => [
  { k: 'Mode', v: mode.value === 'auto' ? 'Auto' : 'Manual' },
  { k: 'Default algorithm', v: mode.value === 'auto' ? 'Auto-selected' : (selectedConfig.value ? `${selectedConfig.value.name} · ${selectedConfig.value.algorithm}` : '—') },
  { k: 'Training dataset', v: calibrationDataset.value?.name ?? '—' },
  { k: 'Targets', v: targetCols.value.length ? targetCols.value.join(', ') : '—' },
  { k: 'Sectors', v: selectedSectors.value.length ? `${selectedSectors.value.length} of ${availableSectors.value.length}` : 'None' },
  { k: 'Segments', v: mode.value === 'auto' ? 'Automatic' : (selectedConfig.value ? `${selectedConfig.value.split_by} ≤${selectedConfig.value.max_segments}` : '—') }
])

const submitting = ref(false)
const canLaunch = computed(() =>
  mode.value === 'manual' &&
  !!calibrationDataset.value &&
  !!forecastDataset.value &&
  targetCols.value.length > 0 &&
  !!selectedConfigId.value &&
  !!modelName.value.trim()
)

const launch = async () => {
  if (mode.value === 'auto') {
    toast.add({ severity: 'warn', summary: 'Auto training unavailable', detail: 'Auto mode is not wired up to the backend yet — switch to Manual to launch a run.', life: 4500 })
    return
  }
  if (!canLaunch.value) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Fill in the model name, at least one target column and a model configuration.', life: 3500 })
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
      name: modelName.value.trim(),
      model_config_id: cfg.id,
      feature_cols: featureCols.value,
      targets: targetCols.value.map((t) => {
        const ov = targetOverrides.value[t]
        return ov ? { target_col: t, model_config_id: ov.model_config_id, feature_cols: ov.feature_cols } : { target_col: t }
      }),
      segmentation: selectedSectors.value.length > 0
        ? {
            sectors: selectedSectors.value,
            split_by: cfg.split_by,
            max_segments: cfg.max_segments,
            ...(Object.keys(sectorOverridesPayload).length ? { sector_overrides: sectorOverridesPayload } : {})
          }
        : null,
      analysis: analysisParams.value
    }
    const { data } = await workflowsAPI.create(payload)
    toast.add({ severity: 'success', summary: 'Workflow queued', detail: `Run ${data.run_id}`, life: 3000 })
    resetNewModelForm()
    router.push({ name: 'jobs_workflow', params: { run_id: data.run_id } })
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
    await Promise.all([fetchResolvedDatasets(), fetchConfigs()])
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
})
onUnmounted(() => { loaded = false })
</script>

<template>
  <div class="model-new">
    <PageHeader eyebrow="MODEL" title="New Model" subtitle="Build, train and analyze a segmented model in one flow" />

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

    <!-- 01 Data sources (read-only, resolved server-side) -->
    <div class="step-card card--emphasis">
      <div class="step-head">
        <span class="step-badge font-mono">01</span>
        <span class="step-title">Data sources</span>
      </div>
      <div v-if="loadingDatasets" class="grid-caption"><i class="pi pi-spin pi-spinner" /> Resolving latest datasets…</div>
      <div v-else class="source-grid">
        <div v-for="row in dataSourceRows" :key="row.key" class="source-row">
          <div class="source-label">{{ row.label }}<span v-if="!row.required" class="grid-caption source-optional">(optional)</span></div>
          <div v-if="row.ds" class="source-value">
            <span class="font-mono source-name">{{ row.ds.name }}</span>
            <span class="grid-caption">{{ row.ds.row_count?.toLocaleString() }} rows · {{ fmtDate(row.ds.created_at) }}</span>
            <span class="text-link" @click="router.push({ name: 'dataset_view', params: { id: row.ds.id } })">View &rarr;</span>
          </div>
          <span v-else class="tag-warn">NONE UPLOADED</span>
        </div>
      </div>
      <div class="grid-caption mt-2">The most recently uploaded dataset per type is used automatically. Upload a new dataset under Datasets to change it.</div>
    </div>

    <!-- 02 Targets & sectors -->
    <div class="step-card card--emphasis">
      <div class="step-head">
        <span class="step-badge font-mono">02</span>
        <span class="step-title">Targets &amp; sectors</span>
      </div>
      <div class="field-label">Target columns</div>
      <EySelect
        v-model="targetCols" :options="targetColumnOptions" placeholder="Select target columns"
        :disabled="targetColumnOptions.length === 0" :multiple="true"
        class="w-full font-mono mb-3" :filter="true" :showToggleAll="true"
        :triggerLabel="targetCols.length ? targetsTriggerLabel : null"
      />
      <div v-if="targetCols.length" class="target-chip-row">
        <span v-for="t in targetCols" :key="t" class="tag-outline target-chip">
          <span class="font-mono">{{ t }}</span><span v-if="objectiveFor(t)" class="target-chip-objective">{{ objectiveFor(t) }}</span>
        </span>
      </div>
      <div class="grid-caption mt-2">One calibration run is trained per target. Include total_assets, total_shortterm_debts and total_longterm_debts to also run credit analysis.</div>

      <div class="field-label mt-4">Sectors to model</div>
      <div v-if="loadingSectors" class="grid-caption"><i class="pi pi-spin pi-spinner" /> Loading sectors…</div>
      <EySelect
        v-else
        v-model="selectedSectors" :options="availableSectors"
        :disabled="!calibrationDataset || availableSectors.length === 0"
        :multiple="true" :showToggleAll="true"
        :placeholder="sectorsTriggerLabel"
        :triggerLabel="selectedSectors.length ? sectorsTriggerLabel : null"
        class="w-full" filter
      />
      <div class="grid-caption mt-2">A separate segmented model is trained for each selected sector, per target</div>
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
            <EySelect v-model="optimizationMetric" :options="OPTIMIZATION_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
          </div>
          <div class="field-col">
            <label class="field-label">Training budget</label>
            <EySelect v-model="trainingBudget" :options="BUDGET_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
          </div>
        </div>
      </template>

      <!-- Manual -->
      <template v-else>
        <div class="field-row-baseline mb-2">
          <label class="field-label">Default configuration</label>
          <div class="spacer" />
          <span class="text-link" @click="router.push({ name: 'model_configurations' })">Manage configurations &rarr;</span>
        </div>
        <EySelect v-model="selectedConfigId" :options="configs" optionValue="id" placeholder="Select a configuration" class="w-full mb-3" :filter="true">
          <template #value="{ option }">
            <span v-if="option" class="cfg-value">
              <span class="font-mono">{{ option.name }}</span>
              <span class="tag-fill cfg-algo-tag">{{ option.algorithm }}</span>
            </span>
          </template>
          <template #option="{ option }">
            <span class="cfg-option">
              <span class="font-mono cfg-option-name">{{ option.name }}</span>
              <span class="tag-outline">{{ option.algorithm }}</span>
            </span>
          </template>
        </EySelect>
        <div v-if="configs.length === 0" class="grid-caption mb-3">No configurations saved yet — <span class="text-link" @click="router.push({ name: 'model_configurations' })">create one</span>.</div>

        <div v-if="selectedConfig" class="inset-strip mb-4">
          <div class="inset-field"><span class="inset-label">Split</span><span class="font-mono inset-value">{{ Math.round((selectedConfig.train_split ?? 0.8) * 100) }}/{{ 100 - Math.round((selectedConfig.train_split ?? 0.8) * 100) }}</span></div>
          <div class="inset-field"><span class="inset-label">Segmentation</span><span class="font-mono inset-value">{{ selectedConfig.split_by }} &le;{{ selectedConfig.max_segments }}</span></div>
          <div class="inset-field"><span class="inset-label">Scaler</span><span class="font-mono inset-value">{{ selectedConfig.scaler || 'None' }}</span></div>
          <div class="inset-field"><span class="inset-label">Search</span><span class="font-mono inset-value">{{ selectedConfig.search_config_json ? (JSON.parse(selectedConfig.search_config_json).mode === 'random' ? 'Randomized' : 'Grid') : 'Off' }}</span></div>
        </div>

        <div class="field-row-baseline mb-2">
          <label class="field-label">Default feature columns</label>
          <div class="spacer" />
          <span class="text-link" @click="router.push({ name: 'model_feature_selection' })">Advanced feature selection &rarr;</span>
        </div>
        <EySelect
          v-model="featureCols" :options="featureOptions" :disabled="!targetCols.length"
          :multiple="true" :showToggleAll="true" class="w-full font-mono"
          :placeholder="featsTriggerLabel" :triggerLabel="featsTriggerLabel" filter
        />
        <div class="grid-caption mt-2 mb-4">Numeric columns present in the forecast dataset, excluding target columns, are used by default</div>

        <div class="divider" />
        <div class="collapsible-header" @click="toggleTargetSection">
          <i class="pi collapse-caret" :class="showTargetOverrides ? 'pi-chevron-down' : 'pi-chevron-right'" />
          <label class="field-label collapsible-label">Per-target configuration</label>
          <span class="grid-caption">The configuration above applies to all targets — customize a target to override it</span>
          <div class="spacer" />
          <span v-if="targetOverrideCount" class="tag-outline tag-outline--custom">{{ targetOverrideCount }} customized</span>
        </div>
        <template v-if="showTargetOverrides">
          <div v-for="row in perTargetRows" :key="row.name" class="ps-row">
            <div class="ps-name">{{ row.name }}</div>
            <span class="tag-outline" :class="{ 'tag-outline--custom': row.isCustom }">{{ row.tag }}</span>
            <div class="font-mono ps-summary">{{ row.summary }}</div>
            <span v-if="row.isCustom" class="text-link text-link--danger" @click="resetTargetOverride(row.name)">Reset</span>
            <span class="text-link" @click="toggleCustomizeTarget(row.name)">{{ row.actionLabel }}</span>
          </div>
          <div v-if="customizingTarget" class="ps-override-panel">
            <div class="field-row-baseline mb-3">
              <span class="eyebrow">OVERRIDE — <span class="font-mono">{{ customizingTarget }}</span></span>
              <div class="spacer" />
              <span class="text-link" @click="router.push({ name: 'model_configurations' })">Manage configurations &rarr;</span>
            </div>
            <div class="field-grid-2 mb-3">
              <div class="field-col">
                <label class="field-label">Configuration</label>
                <EySelect v-model="targetOverrideDraft.model_config_id" :options="configs" optionValue="id" class="w-full" :filter="true">
                  <template #value="{ option }">
                    <span v-if="option" class="cfg-value">
                      <span class="font-mono">{{ option.name }}</span>
                      <span class="tag-outline">{{ option.algorithm }}</span>
                    </span>
                  </template>
                  <template #option="{ option }">
                    <span class="cfg-option">
                      <span class="font-mono cfg-option-name">{{ option.name }}</span>
                      <span class="tag-outline">{{ option.algorithm }}</span>
                    </span>
                  </template>
                </EySelect>
              </div>
              <div class="field-col">
                <label class="field-label">Feature columns</label>
                <EySelect v-model="targetOverrideDraft.feature_cols" :options="featureOptions" :multiple="true" :showToggleAll="true" class="w-full font-mono" :placeholder="targetOverrideFeatsLabel" :triggerLabel="targetOverrideFeatsLabel" filter />
              </div>
            </div>
            <div class="ps-override-footer">
              <span class="grid-caption">Overrides the configuration and feature columns for this target only</span>
              <div class="spacer" />
              <Button label="Cancel" outlined size="small" @click="cancelTargetOverride" />
              <Button class="btn-cta" size="small" @click="applyTargetOverride(customizingTarget)">Apply override</Button>
            </div>
          </div>
        </template>

        <template v-if="selectedSectors.length">
          <div class="divider" />
          <div class="collapsible-header" @click="toggleSectorSection">
            <i class="pi collapse-caret" :class="showSectorOverrides ? 'pi-chevron-down' : 'pi-chevron-right'" />
            <label class="field-label collapsible-label">Per-sector configuration</label>
            <span class="grid-caption">Applies within every target — customize a sector to override it</span>
            <div class="spacer" />
            <span v-if="sectorOverrideCount" class="tag-outline tag-outline--custom">{{ sectorOverrideCount }} customized</span>
          </div>
          <template v-if="showSectorOverrides">
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
                  <EySelect v-model="overrideDraft.model_config_id" :options="configs" optionValue="id" class="w-full" :filter="true">
                    <template #value="{ option }">
                      <span v-if="option" class="cfg-value">
                        <span class="font-mono">{{ option.name }}</span>
                        <span class="tag-outline">{{ option.algorithm }}</span>
                      </span>
                    </template>
                    <template #option="{ option }">
                      <span class="cfg-option">
                        <span class="font-mono cfg-option-name">{{ option.name }}</span>
                        <span class="tag-outline">{{ option.algorithm }}</span>
                      </span>
                    </template>
                  </EySelect>
                </div>
                <div class="field-col">
                  <label class="field-label">Feature columns</label>
                  <EySelect v-model="overrideDraft.feature_cols" :options="overrideFeatureOptions" :multiple="true" :showToggleAll="true" class="w-full font-mono" :placeholder="overrideFeatsLabel" :triggerLabel="overrideFeatsLabel" filter />
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
        </template>
      </template>
    </div>

    <!-- 04 Review & launch -->
    <div class="step-card card--emphasis">
      <div class="step-head">
        <span class="step-badge font-mono">04</span>
        <span class="step-title">Review &amp; launch</span>
      </div>
      <div class="field-col mb-4">
        <label class="field-label">Workflow name</label>
        <InputText v-model="modelName" placeholder="e.g. std_q3_experiment" class="w-full" />
      </div>

      <div class="pipeline-strip">
        <div class="pipeline-stage"><span class="pipeline-stage-num">1</span>Train ({{ targetCols.length || 0 }} target{{ targetCols.length === 1 ? '' : 's' }})</div>
        <span class="pipeline-arrow">&rarr;</span>
        <div class="pipeline-stage"><span class="pipeline-stage-num">2</span>Forecast ({{ targetCols.length || 0 }} run{{ targetCols.length === 1 ? '' : 's' }})</div>
        <span class="pipeline-arrow">&rarr;</span>
        <div class="pipeline-stage">
          <span class="pipeline-stage-num">3</span>Credit analysis
          <span class="tag-fill pipeline-tag" :class="{ 'pipeline-tag--skip': !analysisWillRun }">{{ analysisWillRun ? 'READY' : 'SKIPPED' }}</span>
        </div>
      </div>
      <div v-if="!analysisWillRun" class="grid-caption mt-2">{{ analysisStageLabel }}</div>

      <div v-if="analysisWillRun" class="field-grid-2 mt-4">
        <div class="field-col">
          <label class="field-label">Exposure (EAD)</label>
          <InputNumber v-model="analysisParams.exposure" mode="decimal" class="w-full" />
        </div>
        <div class="field-col">
          <label class="field-label">Discount rate</label>
          <InputNumber v-model="analysisParams.discount_rate" mode="decimal" :minFractionDigits="2" :maxFractionDigits="4" class="w-full" />
        </div>
        <div class="field-col">
          <label class="field-label">Lifetime horizon (years)</label>
          <InputNumber v-model="analysisParams.lifetime_horizon" class="w-full" />
        </div>
        <div class="field-col">
          <label class="field-label">PD curve</label>
          <EySelect v-model="analysisParams.curve" :options="[{ label: 'Moody\'s', value: 'moodys' }]" optionLabel="label" optionValue="value" class="w-full" />
        </div>
      </div>

      <div class="summary-strip mt-4">
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
        <span>Start workflow</span>
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
.tag-warn { display: inline-flex; align-items: center; border: 1px solid var(--error-color); color: var(--error-text-color); font-size: 9.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 7px; border-radius: 2px; }

.step-card { padding: 20px 22px; margin-bottom: 16px; }
.step-head { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.step-badge { width: 26px; height: 26px; flex-shrink: 0; background: var(--ink); color: var(--yellow); border-radius: 2px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }
.step-title { font-size: 15px; font-weight: 700; flex: 1; }
.step-mode-tag { margin-left: auto; }

.source-grid { display: flex; flex-direction: column; gap: 0; }
.source-row { display: flex; align-items: center; gap: 16px; min-height: 44px; border-bottom: 1px solid var(--surface-border-row); padding: 6px 2px; }
.source-row:last-child { border-bottom: none; }
.source-label { width: 220px; flex: none; font-size: 13px; font-weight: 600; }
.source-optional { margin-left: 6px; font-weight: 400; }
.source-value { display: flex; align-items: baseline; gap: 10px; }
.source-name { font-size: 13px; font-weight: 600; }

.target-chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.target-chip { gap: 6px; }
.target-chip-objective { color: var(--text-color-muted-2); font-weight: 600; text-transform: none; letter-spacing: 0; }

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

.collapsible-header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; cursor: pointer; }
.collapse-caret { align-self: center; font-size: 11px; color: var(--text-color-muted); }
.collapsible-header:hover .collapse-caret { color: var(--ink); }
.collapsible-label { margin-bottom: 0; cursor: pointer; }

.ps-row { display: flex; align-items: center; gap: 12px; min-height: 44px; border-bottom: 1px solid var(--surface-border-row); padding: 4px 2px; }
.ps-name { width: 180px; flex: none; font-size: 13px; font-weight: 600; }
.ps-summary { flex: 1; font-size: 11.5px; color: var(--text-color-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.ps-override-panel { background: var(--surface-inset); border-radius: 2px; padding: 14px 16px; margin-top: 4px; }
.ps-override-footer { display: flex; align-items: center; gap: 12px; margin-top: 4px; }

.pipeline-strip { display: flex; align-items: center; gap: 12px; background: var(--surface-inset); border-radius: 2px; padding: 14px 18px; flex-wrap: wrap; }
.pipeline-stage { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; }
.pipeline-stage-num { width: 20px; height: 20px; border-radius: 50%; background: var(--ink); color: var(--yellow); font-size: 10.5px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }
.pipeline-arrow { color: var(--text-color-muted-2); font-size: 14px; }
.pipeline-tag { margin-left: 4px; }
.pipeline-tag--skip { background: var(--surface-border-input); color: var(--text-color-secondary); }

.summary-strip { display: flex; flex-wrap: wrap; gap: 24px; background: var(--surface-inset); border-radius: 2px; padding: 14px 18px; }
.summary-field { display: flex; flex-direction: column; gap: 3px; }

.footer-bar { position: sticky; bottom: 0; display: flex; align-items: center; gap: 12px; background: var(--surface-card); border-top: 1px solid var(--surface-border); padding: 14px 4px; margin-top: 8px; }
.footer-spacer { flex: 1; }
.footer-note { color: var(--text-color-muted); }
.btn-play { color: var(--yellow); margin-right: 6px; }
</style>
