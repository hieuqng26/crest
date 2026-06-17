<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { FilterMatchMode } from 'primevue/api'
import datasetsAPI from '@/api/datasetsAPI'
import { getDataset, fetchDatasets, datasets } from './datasetsStore'
import { fmtDate as formatDate } from '@/utils/datetime'

const props = defineProps({ id: { type: [String, Number], required: true } })
const router = useRouter()
const route  = useRoute()
const toast  = useToast()

const backRoute = computed(() => route.query.back ? { name: route.query.back } : { name: 'datasets' })

const dataset = computed(() => getDataset(props.id))

const rows = ref([])
const loadingRows = ref(false)
const first = ref(0)
const pageSize = ref(50)
const sortField = ref(null)
const sortOrder = ref(null)
const filters = ref({ global: { value: '', matchMode: FilterMatchMode.CONTAINS } })
const totalOverride = ref(null)

const visibleCols = ref([])
const colOptions = computed(() => (dataset.value?.columns ?? []).map(c => ({ label: c, value: c })))
const orderedVisible = computed(() => (dataset.value?.columns ?? []).filter(c => visibleCols.value.includes(c)))
const totalRecords = computed(() => totalOverride.value ?? dataset.value?.row_count ?? 0)

const sourceSeverity = (s) => (s === 'upload' ? 'info' : 'warning')
const statusSeverity = (s) => ({ ready: 'success', processing: 'warning', error: 'danger' }[s] ?? 'secondary')

onMounted(async () => {
  if (!dataset.value) await fetchDatasets()
  if (dataset.value) {
    visibleCols.value = dataset.value.columns
    loadRows()
  }
})

const loadRows = async () => {
  if (!dataset.value) return
  loadingRows.value = true
  try {
    const { data } = await datasetsAPI.rows(dataset.value.id, {
      offset: first.value,
      limit: pageSize.value,
      sort: sortField.value,
      order: sortOrder.value === 1 ? 'asc' : sortOrder.value === -1 ? 'desc' : null,
      filter: filters.value.global.value?.toString().trim() || ''
    })
    rows.value = Array.isArray(data) ? data : (data.rows ?? [])
    if (!Array.isArray(data) && data.total != null) totalOverride.value = data.total
  } catch {
    rows.value = []
  } finally {
    loadingRows.value = false
  }
}

const onPage   = (e) => { first.value = e.first; pageSize.value = e.rows; loadRows() }
const onSort   = (e) => { sortField.value = e.sortField; sortOrder.value = e.sortOrder; loadRows() }
const onFilter = ()  => { first.value = 0; loadRows() }

const downloadCsv = () => {
  if (!dataset.value) return
  const cols = orderedVisible.value
  const header = cols.join(',')
  const body = rows.value.map(r => cols.map(c => JSON.stringify(r[c] ?? '')).join(',')).join('\n')
  const blob = new Blob([header + '\n' + body], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `${dataset.value.name}_page.csv`; a.click()
  URL.revokeObjectURL(url)
  toast.add({ severity: 'info', summary: 'Exported current page', life: 2000 })
}
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
          <div class="text-xl font-semibold">{{ totalRecords.toLocaleString() }}</div>
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
      <div class="flex flex-wrap align-items-center gap-3 mb-3">
        <IconField class="flex-1" style="min-width: 18rem">
          <InputIcon class="pi pi-search" />
          <InputText
            v-model="filters.global.value"
            placeholder="Search rows…"
            class="w-full"
            @input="onFilter"
          />
        </IconField>
        <MultiSelect
          v-model="visibleCols"
          :options="colOptions"
          optionLabel="label"
          optionValue="value"
          display="chip"
          placeholder="Columns"
          class="w-18rem"
        />
        <Button label="Export page" icon="pi pi-download" size="small" text @click="downloadCsv" />
      </div>

      <DataTable
        :value="rows"
        :lazy="true"
        :loading="loadingRows"
        :paginator="true"
        :rows="pageSize"
        :first="first"
        :totalRecords="totalRecords"
        :rowsPerPageOptions="[10, 25, 50, 100, 250]"
        :sortField="sortField"
        :sortOrder="sortOrder"
        size="small"
        scrollable
        scrollHeight="60vh"
        @page="onPage"
        @sort="onSort"
        currentPageReportTemplate="{first}–{last} of {totalRecords}"
        :paginatorTemplate="'FirstPageLink PrevPageLink CurrentPageReport NextPageLink LastPageLink RowsPerPageDropdown'"
        :alwaysShowPaginator="true"
      >
        <Column field="__idx" header="#" style="width:5rem" frozen />
        <Column
          v-for="col in orderedVisible"
          :key="col"
          :field="col"
          :header="col"
          sortable
          style="min-width: 10rem"
        >
          <template #body="{ data }">
            <span class="font-mono text-sm">{{ data[col] }}</span>
          </template>
        </Column>
      </DataTable>
    </div>
  </div>

  <div v-else class="p-4 text-center text-color-secondary">
    <i class="pi pi-spin pi-spinner text-3xl block mb-2" />
    <p class="m-0">Loading dataset…</p>
  </div>
</template>
