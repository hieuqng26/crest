<script setup>
import { computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import datasetsAPI from '@/api/datasetsAPI'
import { getDataset, fetchDatasets, datasets } from './datasetsStore'
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

<template>
  <div v-if="dataset" class="p-4">

    <!-- Header -->
    <div class="flex align-items-center gap-3 mb-4">
      <Button icon="pi pi-arrow-left" text rounded @click="router.push(backRoute)" />
      <div class="flex-1 min-w-0">
        <div class="text-xs text-color-secondary uppercase" style="letter-spacing: 0.06em">Dataset</div>
        <h2 class="text-2xl font-semibold m-0 white-space-nowrap overflow-hidden text-overflow-ellipsis">
          {{ dataset.name }}
        </h2>
      </div>
      <Tag
        :value="dataset.source === 'live_query' ? 'Live Query' : 'Upload'"
        :severity="sourceSeverity(dataset.source)"
      />
      <Tag :value="dataset.status" :severity="statusSeverity(dataset.status)" />
    </div>

    <!-- Metadata strip -->
    <div class="surface-card border-round shadow-1 mb-4" style="padding: 0">
      <div class="flex flex-wrap" style="gap: 0">
        <div class="flex flex-column justify-content-center p-4" style="min-width: 10rem; border-right: 1px solid var(--surface-border)">
          <div class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">Total Rows</div>
          <div class="text-xl font-semibold">{{ (dataset.row_count ?? 0).toLocaleString() }}</div>
        </div>
        <div class="flex flex-column justify-content-center p-4" style="min-width: 10rem; border-right: 1px solid var(--surface-border)">
          <div class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">Columns</div>
          <div class="text-xl font-semibold">{{ dataset.columns.length }}</div>
        </div>
        <div class="flex flex-column justify-content-center p-4" style="min-width: 12rem; border-right: 1px solid var(--surface-border)">
          <div class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">Created</div>
          <div class="text-xl font-semibold">{{ formatDate(dataset.created_at) }}</div>
        </div>
        <div class="flex flex-column justify-content-center p-4">
          <div class="text-xs text-color-secondary uppercase mb-1" style="letter-spacing: 0.06em">Created By</div>
          <div class="text-xl font-semibold">{{ dataset.created_by }}</div>
        </div>
      </div>
    </div>

    <!-- Data table -->
    <div class="surface-card border-round shadow-1 p-4">
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
