<script setup>
import { ref, onMounted } from 'vue'
import calibrationsAPI from '@/api/calibrationsAPI'

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

    <DataTable
      v-else
      :value="segments"
      sortField="ead_total"
      :sortOrder="-1"
      responsiveLayout="scroll"
      class="p-datatable-sm"
    >
      <Column field="sector" header="Sector" sortable />
      <Column field="split_by" header="Split By" style="width: 8rem">
        <template #body="{ data }">
          <Tag :value="data.split_by" severity="secondary" />
        </template>
      </Column>
      <Column field="split_value" header="Split Value" sortable />
      <Column field="row_count" header="Rows" sortable style="width: 6rem">
        <template #body="{ data }">{{ data.row_count.toLocaleString() }}</template>
      </Column>
      <Column field="ead_total" header="EAD Total" sortable style="width: 8rem">
        <template #body="{ data }">{{ fmtEad(data.ead_total) }}</template>
      </Column>
      <Column header="Primary Metric" style="width: 10rem">
        <template #body="{ data }">
          <span v-if="primaryMetric(data)" class="font-mono text-sm">
            {{ primaryMetric(data).label }}: {{ primaryMetric(data).value.toFixed(3) }}
          </span>
          <span v-else class="text-color-secondary text-xs">—</span>
        </template>
      </Column>
      <Column field="status" header="Status" sortable style="width: 7rem">
        <template #body="{ data }">
          <Tag :value="data.status" :severity="STATUS_SEV[data.status] ?? 'secondary'" />
        </template>
      </Column>
      <Column header="" style="width: 5rem">
        <template #body="{ data }">
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
      </Column>
    </DataTable>
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
