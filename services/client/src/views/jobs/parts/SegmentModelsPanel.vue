<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import StatusDot from '@/components/ui/StatusDot.vue'
import EySelect from '@/components/ui/EySelect.vue'
import BaseTable from '@/views/composables/BaseTable.vue'

const props = defineProps({ runId: { type: String, required: true } })
const toast = useToast()

const segments = ref([])
const loading = ref(true)
const search = ref('')

// Run-level defaults + feature universe the customize panel offers as a baseline.
const defaultConfigId = ref(null)
const defaultFeatureCols = ref([])
const featureOptions = ref([])

const fetchSegments = async () => {
  try {
    const { data } = await calibrationsAPI.segments(props.runId)
    segments.value = data.segments ?? []
    defaultConfigId.value = data.default_model_config_id ?? null
    defaultFeatureCols.value = data.default_feature_cols ?? []
    featureOptions.value = data.feature_options ?? []
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load segments', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}

let pollTimer = null
const hasRetraining = computed(() => segments.value.some((s) => s.status === 'queued' || s.status === 'running'))
const startPolling = () => { if (!pollTimer) pollTimer = setInterval(async () => { if (!hasRetraining.value) { stopPolling(); return } await fetchSegments() }, 3000) }
const stopPolling = () => { clearInterval(pollTimer); pollTimer = null }

onMounted(async () => {
  loading.value = true
  await fetchSegments()
  loading.value = false
  if (hasRetraining.value) startPolling()
})
onUnmounted(stopPolling)

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return segments.value
    .filter((s) => !q || (s.sector + s.split_value).toLowerCase().includes(q))
    .sort((a, b) => (b.row_count ?? 0) - (a.row_count ?? 0))
})

const fmtMetric = (v) => (v == null ? '—' : Number(v).toFixed(4))

const SEG_COLS = [
  { field: 'sector', label: 'SECTOR', width: '160px' },
  { field: 'segment', label: 'SEGMENT' },
  { field: 'n', label: 'N', align: 'right', width: '70px' },
  { field: 'r2', label: 'R²', align: 'right', width: '90px' },
  { field: 'rmse', label: 'RMSE', align: 'right', width: '90px' },
  { field: 'status', label: 'STATUS', width: '130px' },
  { field: 'action', label: 'ACTION', align: 'right', width: '110px' },
]

// ── customize panel ─────────────────────────────────────────────────────────
// Mirrors New Model's per-sector override: pick a saved configuration and a
// subset of feature columns. `overrideDraft` holds { model_config_id, feature_cols }.
const customizingKey = ref(null)
const configs = ref([])
const overrideDraft = ref({ model_config_id: null, feature_cols: [] })
const submitting = ref(false)

onMounted(async () => {
  try {
    const { data } = await modelConfigsAPI.list()
    configs.value = data ?? []
  } catch {
    configs.value = []
  }
})

const toggleCustomize = (seg) => {
  if (customizingKey.value === seg.segment_key) {
    customizingKey.value = null
    return
  }
  customizingKey.value = seg.segment_key
  overrideDraft.value = {
    // Fall back to this segment's own config, then the run default.
    model_config_id: seg.model_config_id ?? defaultConfigId.value,
    // A persisted override wins; otherwise start from the run's default feature set.
    feature_cols: seg.feature_cols ? [...seg.feature_cols] : [...defaultFeatureCols.value]
  }
}

const cancelCustomize = () => { customizingKey.value = null }

const overrideFeatsLabel = computed(() => {
  const n = overrideDraft.value.feature_cols?.length ?? 0
  return n === featureOptions.value.length
    ? `All features (${featureOptions.value.length})`
    : `${n} of ${featureOptions.value.length} features`
})

// With a `dataKey` set, PrimeVue 3 keys `expandedRows` by that value as a map
// ({ [segment_key]: true }), NOT an array of row objects. Only one customize
// panel is open at a time.
const expandedRows = computed(() =>
  customizingKey.value ? { [customizingKey.value]: true } : {}
)

const rerunSegment = async (seg) => {
  submitting.value = true
  try {
    const { data } = await calibrationsAPI.rerunSegment(props.runId, seg.segment_key, {
      model_config_id: overrideDraft.value.model_config_id,
      feature_cols: overrideDraft.value.feature_cols
    })
    const idx = segments.value.findIndex((s) => s.segment_key === seg.segment_key)
    if (idx >= 0) segments.value[idx] = { ...segments.value[idx], ...data }
    customizingKey.value = null
    startPolling()
    toast.add({ severity: 'info', summary: 'Segment queued', detail: `${seg.sector} · ${seg.split_value}`, life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Re-run failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="panel">
    <div class="segments-header">
      <h3>Segment models</h3>
      <span class="segments-caption">{{ segments.length }} segments</span>
      <div class="spacer" />
      <InputText v-model="search" placeholder="Search segments…" class="segments-search" />
    </div>

    <BaseTable
      :columns="SEG_COLS"
      :value="filtered"
      dataKey="segment_key"
      :expandedRows="expandedRows"
      :rowClass="(seg) => customizingKey === seg.segment_key ? 'seg-row--open' : ''"
    >
      <template #empty>
        <div v-if="!loading" class="empty-state">
          <i class="pi pi-th-large" />
          <p>No segment results yet.</p>
        </div>
      </template>

      <template #cell-sector="{ row: seg }">
        <span class="seg-sector">{{ seg.sector }}</span>
      </template>
      <template #cell-segment="{ row: seg }">
        <span class="font-mono seg-value">{{ seg.split_value }}</span>
      </template>
      <template #cell-n="{ row: seg }">
        <span class="font-mono">{{ seg.row_count ?? '—' }}</span>
      </template>
      <template #cell-r2="{ row: seg }">
        <span class="font-mono seg-r2">{{ fmtMetric(seg.train_metrics?.r2) }}</span>
      </template>
      <template #cell-rmse="{ row: seg }">
        <span class="font-mono seg-rmse">{{ fmtMetric(seg.train_metrics?.rmse) }}</span>
      </template>
      <template #cell-status="{ row: seg }">
        <StatusDot :status="seg.status === 'queued' || seg.status === 'running' ? 'running' : seg.status" :label="seg.status === 'queued' || seg.status === 'running' ? 'Re-training' : undefined" />
      </template>
      <template #cell-action="{ row: seg }">
        <span
          class="customize-link"
          :class="{ 'is-disabled': seg.status === 'queued' || seg.status === 'running' }"
          @click="!(seg.status === 'queued' || seg.status === 'running') && toggleCustomize(seg)"
        >{{ customizingKey === seg.segment_key ? 'Close' : 'Customize' }}</span>
      </template>

      <template #expansion="{ row: seg }">
        <div class="customize-panel">
          <div class="customize-head">
            <div class="eyebrow customize-title">
              CUSTOMIZE SEGMENT — <span class="font-mono">{{ seg.sector }} · {{ seg.split_value }}</span>
            </div>
            <div class="spacer" />
            <span class="text-link" @click="router.push({ name: 'model_configurations' })">Manage configurations &rarr;</span>
          </div>
          <div class="customize-fields">
            <div class="field">
              <div class="font-mono field-label">configuration</div>
              <EySelect v-model="overrideDraft.model_config_id" :options="configs" optionValue="id" placeholder="Select a configuration" class="w-full" :filter="true">
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
            <div class="field">
              <div class="font-mono field-label">feature columns</div>
              <EySelect
                v-model="overrideDraft.feature_cols" :options="featureOptions"
                :multiple="true" :showToggleAll="true" class="w-full font-mono"
                :placeholder="overrideFeatsLabel" :triggerLabel="overrideFeatsLabel" filter
              />
            </div>
          </div>
          <div class="customize-footer">
            <span class="customize-note">Only this segment is retrained — configuration, features and hyperparameters come from the chosen configuration. All other segment models are kept</span>
            <div class="spacer" />
            <Button label="Cancel" outlined class="btn-cancel-seg" @click="cancelCustomize" />
            <Button class="btn-rerun-seg btn-cta" :loading="submitting" :disabled="!overrideDraft.model_config_id" @click="rerunSegment(seg)">
              <span class="btn-play">▶</span>
              <span>Re-run segment</span>
            </Button>
          </div>
        </div>
      </template>
    </BaseTable>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 0 16px 4px;
}
.segments-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 0;
}
.segments-header h3 { flex: none; }
.segments-caption { font-size: 12px; color: var(--text-color-muted); }
.spacer { flex: 1; }
.segments-search { width: 200px; height: 32px; font-size: 12.5px !important; }

.seg-row--open { background: var(--surface-hover); }

.seg-name-cell { display: flex; flex-direction: column; gap: 1px; }
.seg-sector { font-size: 13px; font-weight: 600; }
.seg-value { font-size: 12px; color: var(--text-color-secondary); }
.seg-r2 { font-weight: 600; }
.seg-rmse { color: var(--text-color-secondary); }

.customize-link {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink);
  cursor: pointer;
  border-bottom: 2px solid var(--yellow);
  padding-bottom: 1px;
  transition: color 0.15s ease;
}
.customize-link:hover { color: var(--ink-3); }
.customize-link.is-disabled {
  color: var(--text-color-muted-2);
  border-bottom-color: transparent;
  cursor: default;
}

.customize-panel {
  background: var(--surface-inset);
  border-bottom: 1px solid var(--surface-border-row);
  padding: 16px 20px;
}
.customize-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
.customize-title { margin-bottom: 0; }
.customize-fields {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 14px;
}
.field { display: flex; flex-direction: column; gap: 5px; }
.field-label { font-size: 11px; color: var(--text-color-muted); }

.cfg-value, .cfg-option { display: flex; align-items: center; gap: 10px; }
.cfg-option-name { flex: 1; }
.tag-outline {
  display: inline-flex; align-items: center;
  border: 1px solid var(--surface-border-input); color: var(--text-color-secondary);
  font-size: 9.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 3px 7px; border-radius: 2px;
}
.text-link {
  font-size: 12px; font-weight: 600; color: var(--text-color-secondary);
  cursor: pointer; border-bottom: 2px solid var(--yellow); padding-bottom: 1px;
}
.text-link:hover { color: var(--text-color); }

.customize-footer { display: flex; align-items: center; gap: 12px; }
.customize-note { font-size: 12px; color: var(--text-color-muted); }
.btn-cancel-seg, .btn-rerun-seg {
  height: 36px;
  font-size: 12.5px;
}
.btn-rerun-seg {
  display: flex;
  align-items: center;
  gap: 8px;
}
.btn-play { color: var(--yellow); }

.empty-state { text-align: center; padding: 40px 0; color: var(--text-color-muted); vertical-align: middle; }
.empty-state i { font-size: 24px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-state p { margin: 0; }
</style>

<!-- Open-row highlight targets the <tr> BaseTable renders (out of scoped reach). -->
<style>
.ey-table.p-datatable .p-datatable-tbody > tr.seg-row--open,
.ey-table.p-datatable .p-datatable-tbody > tr.seg-row--open:hover {
  background: var(--surface-hover);
}
</style>
