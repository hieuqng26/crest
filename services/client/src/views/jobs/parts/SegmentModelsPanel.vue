<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import StatusDot from '@/components/ui/StatusDot.vue'
import BaseTable from '@/views/composables/BaseTable.vue'

const props = defineProps({ runId: { type: String, required: true } })
const toast = useToast()

const segments = ref([])
const loading = ref(true)
const search = ref('')

const fetchSegments = async () => {
  try {
    const { data } = await calibrationsAPI.segments(props.runId)
    segments.value = data.segments ?? []
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
const customizingKey = ref(null)
const registry = ref([])
const hyperparamForm = ref({})
const submitting = ref(false)

onMounted(async () => {
  try {
    const { data } = await modelConfigsAPI.registry()
    registry.value = data
  } catch {
    registry.value = []
  }
})

const algoMeta = (algorithm) => registry.value.find((a) => a.algorithm === algorithm) || null

const toggleCustomize = (seg) => {
  if (customizingKey.value === seg.segment_key) {
    customizingKey.value = null
    return
  }
  customizingKey.value = seg.segment_key
  const meta = algoMeta(seg.algorithm)
  const defaults = Object.fromEntries((meta?.params ?? []).map((p) => [p.name, p.default]))
  hyperparamForm.value = { ...defaults, ...(seg.hyperparams ?? {}) }
}

const cancelCustomize = () => { customizingKey.value = null }

// PrimeVue DataTable expects the expanded *row objects*; derive them from the
// single open segment key (only one customize panel is open at a time).
const expandedRows = computed(() => {
  const seg = filtered.value.find((s) => s.segment_key === customizingKey.value)
  return seg ? [seg] : []
})

const rerunSegment = async (seg) => {
  submitting.value = true
  try {
    const { data } = await calibrationsAPI.rerunSegment(props.runId, seg.segment_key, {
      hyperparams: hyperparamForm.value
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
          <div class="eyebrow customize-title">
            CUSTOMIZE SEGMENT — <span class="font-mono">{{ seg.sector }} · {{ seg.split_value }}</span>
          </div>
          <div class="customize-fields">
            <div class="field">
              <div class="font-mono field-label">algorithm</div>
              <div class="field-static">{{ seg.algorithm ?? '—' }}</div>
            </div>
            <div v-for="p in algoMeta(seg.algorithm)?.params ?? []" :key="p.name" class="field">
              <div class="font-mono field-label">{{ p.name }}</div>
              <InputText v-if="p.type === 'string'" v-model="hyperparamForm[p.name]" class="w-full field-input" />
              <InputNumber
                v-else-if="p.type === 'float' || p.type === 'int'"
                v-model="hyperparamForm[p.name]"
                :useGrouping="false"
                :minFractionDigits="p.type === 'float' ? 1 : 0"
                :maxFractionDigits="p.type === 'float' ? 6 : 0"
                class="w-full field-input"
                fluid
              />
              <InputSwitch v-else-if="p.type === 'bool'" v-model="hyperparamForm[p.name]" />
            </div>
          </div>
          <div class="customize-footer">
            <span class="customize-note">Only this segment is retrained — all other segment models are kept</span>
            <div class="spacer" />
            <Button label="Cancel" outlined class="btn-cancel-seg" @click="cancelCustomize" />
            <Button class="btn-rerun-seg btn-cta" :loading="submitting" @click="rerunSegment(seg)">
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
.customize-title { margin-bottom: 12px; }
.customize-fields {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}
.field { display: flex; flex-direction: column; gap: 5px; }
.field-label { font-size: 11px; color: var(--text-color-muted); }
.field-static {
  display: flex;
  align-items: center;
  height: 38px;
  background: var(--surface-200);
  border: 1px solid var(--surface-border-input);
  border-radius: 2px;
  padding: 0 12px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-color-secondary);
}
:deep(.field-input) { height: 38px; font-size: 12.5px; }

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
