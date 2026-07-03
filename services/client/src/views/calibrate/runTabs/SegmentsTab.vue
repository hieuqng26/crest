<script setup>
import { ref, onMounted } from 'vue'
import calibrationsAPI from '@/api/calibrationsAPI'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'
import { localFetchPage } from '@/utils/tableQuery'

const props = defineProps({ run: { type: Object, required: true } })
const emit = defineEmits(['select-segment'])

const segments = ref([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await calibrationsAPI.segments(props.run.run_id)
    segments.value = data.segments ?? []
  } finally {
    loading.value = false
  }
})

const segmentColumns = [
  { field: 'sector', header: 'Sector', width: '10rem' },
  { field: 'split_by', header: 'Split By', width: '8rem' },
  { field: 'split_value', header: 'Split Value', width: '10rem' },
  { field: 'row_count', header: 'Rows', width: '6rem', formatter: (v) => v?.toLocaleString() ?? '—' },
  { field: 'ead_total', header: 'EAD Total', width: '8rem', formatter: (v) => fmtEad(v) },
  { field: 'primary_metric', header: 'Primary Metric', width: '10rem', sortable: false, filterable: false },
  { field: 'status', header: 'Status', width: '7rem' },
  { field: 'actions', header: '', width: '5rem', sortable: false, filterable: false }
]
const segmentsFetchPage = localFetchPage(() => segments.value)

const STATUS_SEV = { success: 'success', failed: 'danger', skipped: 'warning' }

const primaryMetric = (seg) => {
  try {
    const m = JSON.parse(seg.val_metrics_json || 'null')
    if (!m) return null
    const key = Object.keys(m).find(k => ['auc_roc', 'r2', 'rmse'].includes(k))
    return key ? { label: key.replace(/_/g, ' ').toUpperCase(), value: m[key] } : null
  } catch { return null }
}

const fmtEad = (v) => {
  if (v == null) return '—'
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}
</script>

<template>
  <div>
    <div v-if="loading" class="text-center py-8 text-color-secondary">
      <i class="pi pi-spin pi-spinner text-2xl block mb-2" />
      Loading segments…
    </div>

    <div v-else-if="segments.length === 0" class="empty-state">
      <i class="pi pi-th-large text-3xl block mb-2 opacity-50" />
      <p class="m-0 text-color-secondary">No segment results yet.</p>
    </div>

    <CommonDataTable
      v-else
      :key="run.run_id"
      :columns="segmentColumns"
      :fetch-page="segmentsFetchPage"
      :initial-page-size="500"
      initial-sort-field="ead_total"
      :initial-sort-order="-1"
      empty-message="No segment results yet."
    >
      <template #cell-split_by="{ data }">
        <Tag :value="data.split_by" severity="secondary" />
      </template>
      <template #cell-primary_metric="{ data }">
        <span v-if="primaryMetric(data)" class="font-mono text-sm">
          {{ primaryMetric(data).label }}: {{ primaryMetric(data).value.toFixed(3) }}
        </span>
        <span v-else class="text-color-secondary text-xs">—</span>
      </template>
      <template #cell-status="{ data }">
        <Tag :value="data.status" :severity="STATUS_SEV[data.status] ?? 'secondary'" />
      </template>
      <template #cell-actions="{ data }">
        <Button
          v-if="data.status === 'success'"
          icon="pi pi-chart-bar"
          text
          rounded
          size="small"
          v-tooltip.top="'View diagnostics'"
          @click="emit('select-segment', data.segment_key)"
        />
      </template>
    </CommonDataTable>
  </div>
</template>

<style scoped>
.empty-state {
  text-align: center;
  padding: 4rem 2rem;
  border: 1px dashed var(--surface-border);
  border-radius: 12px;
}
</style>
