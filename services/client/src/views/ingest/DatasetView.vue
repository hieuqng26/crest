<script setup>
import { computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import datasetsAPI from '@/api/datasetsAPI'
import { getDataset, fetchDatasets } from './datasetsStore'
import { fmtDate as formatDate } from '@/utils/datetime'
import CommonDataTable from '@/components/Table/CommonDataTable.vue'

const props = defineProps({ id: { type: [String, Number], required: true } })
const router = useRouter()
const route  = useRoute()

const backRoute = computed(() => route.query.back ? { name: route.query.back } : { name: 'datasets' })

const dataset = computed(() => getDataset(props.id))

const tableColumns = computed(() => (dataset.value?.columns ?? []).map(c => ({ field: c, header: c, width: '10rem' })))

const sourceSeverity = (s) => (s === 'upload' ? 'info' : 'warning')
const statusSeverity = (s) => ({ ready: 'success', processing: 'warning', error: 'danger' }[s] ?? 'secondary')

onMounted(async () => {
  if (!dataset.value) await fetchDatasets()
})

const fetchPage = (params) => datasetsAPI.rows(dataset.value.id, params)
const fetchDistinct = (column) => datasetsAPI.rowsDistinct(dataset.value.id, column)
</script>

<style scoped>
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: 0;
  padding: 4px 0;
  font-size: 13px;
  color: var(--text-color-muted);
  cursor: pointer;
  margin-bottom: 12px;
}
.back-link:hover { color: var(--text-color); }

.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
}

.meta-strip { display: flex; flex-wrap: wrap; }
.meta-cell {
  flex: 1;
  min-width: 10rem;
  padding: 16px 20px;
  border-right: 1px solid var(--surface-border-row);
}
.meta-cell:last-child { border-right: none; }
.meta-label { margin-bottom: 6px; }
.meta-value { font-size: 19px; font-weight: 600; }
</style>

<template>
  <div v-if="dataset">

    <!-- Header -->
    <button class="back-link" @click="router.push(backRoute)">
      <i class="pi pi-arrow-left text-xs" /><span>Datasets</span>
    </button>
    <div class="flex align-items-center gap-3 mb-4">
      <div class="flex-1 min-w-0">
        <div class="eyebrow mb-1">DATASET</div>
        <h1 class="white-space-nowrap overflow-hidden text-overflow-ellipsis">{{ dataset.name }}</h1>
      </div>
      <Tag
        :value="dataset.source === 'live_query' ? 'Live Query' : 'Upload'"
        :severity="sourceSeverity(dataset.source)"
      />
      <Tag :value="dataset.status" :severity="statusSeverity(dataset.status)" />
    </div>

    <!-- Metadata strip -->
    <div class="panel meta-strip mb-4">
      <div class="meta-cell">
        <div class="eyebrow meta-label">Total rows</div>
        <div class="font-mono meta-value">{{ (dataset.row_count ?? 0).toLocaleString() }}</div>
      </div>
      <div class="meta-cell">
        <div class="eyebrow meta-label">Columns</div>
        <div class="font-mono meta-value">{{ dataset.columns.length }}</div>
      </div>
      <div class="meta-cell">
        <div class="eyebrow meta-label">Created</div>
        <div class="font-mono meta-value">{{ formatDate(dataset.created_at) }}</div>
      </div>
      <div class="meta-cell">
        <div class="eyebrow meta-label">Created by</div>
        <div class="font-mono meta-value">{{ dataset.created_by }}</div>
      </div>
    </div>

    <!-- Data table -->
    <div class="panel p-4">
      <CommonDataTable
        v-if="tableColumns.length"
        :key="dataset.id"
        :columns="tableColumns"
        :fetch-page="fetchPage"
        :fetch-distinct="fetchDistinct"
        scroll-height="60vh"
        empty-message="No rows found."
      />
    </div>
  </div>

  <div v-else class="p-4 text-center text-color-secondary">
    <i class="pi pi-spin pi-spinner text-3xl block mb-2" />
    <p class="m-0">Loading dataset…</p>
  </div>
</template>
