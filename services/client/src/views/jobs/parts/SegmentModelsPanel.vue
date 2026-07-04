<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useToast } from 'primevue/usetoast'
import calibrationsAPI from '@/api/calibrationsAPI'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import StatusDot from '@/components/ui/StatusDot.vue'

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

    <div class="seg-grid seg-grid--head">
      <div>SEGMENT</div><div class="ta-right">N</div><div class="ta-right">R²</div><div class="ta-right">RMSE</div><div>STATUS</div><div class="ta-right">ACTION</div>
    </div>

    <div v-if="!loading && filtered.length === 0" class="empty-state">
      <i class="pi pi-th-large" />
      <p>No segment results yet.</p>
    </div>

    <template v-for="seg in filtered" :key="seg.segment_key">
      <div class="seg-grid seg-grid--row">
        <div class="seg-name-cell">
          <div class="seg-sector">{{ seg.sector }}</div>
          <div class="font-mono seg-value">{{ seg.split_value }}</div>
        </div>
        <div class="font-mono ta-right">{{ seg.row_count ?? '—' }}</div>
        <div class="font-mono ta-right seg-r2">{{ fmtMetric(seg.train_metrics?.r2) }}</div>
        <div class="font-mono ta-right seg-rmse">{{ fmtMetric(seg.train_metrics?.rmse) }}</div>
        <div><StatusDot :status="seg.status === 'queued' || seg.status === 'running' ? 'running' : seg.status" :label="seg.status === 'queued' || seg.status === 'running' ? 'Re-training' : undefined" /></div>
        <div class="ta-right">
          <span
            class="customize-link"
            :class="{ 'is-disabled': seg.status === 'queued' || seg.status === 'running' }"
            @click="!(seg.status === 'queued' || seg.status === 'running') && toggleCustomize(seg)"
          >{{ customizingKey === seg.segment_key ? 'Close' : 'Customize' }}</span>
        </div>
      </div>

      <div v-if="customizingKey === seg.segment_key" class="customize-panel">
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
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
}
.segments-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
}
.segments-header h3 { flex: none; }
.segments-caption { font-size: 12px; color: var(--text-color-muted); }
.spacer { flex: 1; }
.segments-search { width: 200px; height: 32px; font-size: 12.5px !important; }

.seg-grid {
  display: grid;
  grid-template-columns: minmax(190px, 1.3fr) 70px 90px 90px 130px 120px;
  column-gap: 12px;
  align-items: center;
  padding: 4px 16px;
}
.seg-grid--head {
  height: 38px;
  padding-top: 0;
  padding-bottom: 0;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  color: var(--text-color-muted);
}
.seg-grid--row {
  min-height: 48px;
  border-bottom: 1px solid var(--surface-border-row);
}
.seg-grid--row:hover { background: var(--surface-hover); }
.ta-right { text-align: right; }

.seg-name-cell { display: flex; flex-direction: column; gap: 1px; }
.seg-sector { font-size: 13px; font-weight: 600; }
.seg-value { font-size: 10.5px; color: var(--text-color-muted-2); }
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

.empty-state { text-align: center; padding: 40px 0; color: var(--text-color-muted); }
.empty-state i { font-size: 24px; display: block; margin-bottom: 8px; opacity: 0.6; }
.empty-state p { margin: 0; }
</style>
