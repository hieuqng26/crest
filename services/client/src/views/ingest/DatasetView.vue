<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { FilterMatchMode } from 'primevue/api'
import datasetsAPI from '@/api/datasetsAPI'
import { getDataset, fetchDatasets, datasets } from './datasetsStore'

const props = defineProps({ id: { type: [String, Number], required: true } })
const router = useRouter()
const toast = useToast()

const dataset = computed(() => getDataset(props.id))

// Lazy table state
const rows = ref([])
const loading = ref(false)
const first = ref(0)
const pageSize = ref(50)
const sortField = ref(null)
const sortOrder = ref(null)
const filters = ref({ global: { value: '', matchMode: FilterMatchMode.CONTAINS } })

const visibleCols = ref(dataset.value?.columns ?? [])
const colOptions = computed(() => (dataset.value?.columns ?? []).map(c => ({ label: c, value: c })))
const orderedVisible = computed(() => (dataset.value?.columns ?? []).filter(c => visibleCols.value.includes(c)))

onMounted(async () => {
  if (!dataset.value) await fetchDatasets()
  if (dataset.value) {
    visibleCols.value = dataset.value.columns
    loadRows()
  }
})

const loadRows = async () => {
  if (!dataset.value) return
  loading.value = true
  try {
    const { data } = await datasetsAPI.rows(dataset.value.id, {
      offset: first.value,
      limit: pageSize.value,
      sort: sortField.value,
      order: sortOrder.value === 1 ? 'asc' : sortOrder.value === -1 ? 'desc' : null,
      filter: filters.value.global.value?.toString().trim() || ''
    })
    // Backend returns { rows: [...], total: N }
    rows.value = Array.isArray(data) ? data : (data.rows ?? [])
    if (!Array.isArray(data) && data.total != null) totalOverride.value = data.total
  } catch {
    rows.value = []
  } finally {
    loading.value = false
  }
}

const totalOverride = ref(null)
const totalRecords = computed(() => totalOverride.value ?? dataset.value?.row_count ?? 0)

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

const sourceSeverity = (s) => (s === 'upload' ? 'info' : 'warning')
</script>

<template>
  <div v-if="dataset" class="p-4">
    <div class="flex align-items-center gap-2 mb-4">
      <Button icon="pi pi-arrow-left" text rounded size="small" @click="router.push({ name: 'datasets' })" />
      <div>
        <div class="text-xs text-color-secondary">Datasets</div>
        <h2 class="text-2xl font-semibold m-0">{{ dataset.name }}</h2>
      </div>
    </div>

    <div class="surface-card border-round shadow-1 p-4 mb-4 flex flex-wrap gap-4 align-items-center">
      <div>
        <div class="text-xs text-color-secondary uppercase">Source</div>
        <Tag :value="dataset.source" :severity="sourceSeverity(dataset.source)" class="mt-1" />
      </div>
      <div>
        <div class="text-xs text-color-secondary uppercase">Rows</div>
        <div class="text-lg font-semibold">{{ totalRecords.toLocaleString() }}</div>
      </div>
      <div>
        <div class="text-xs text-color-secondary uppercase">Columns</div>
        <div class="text-lg font-semibold">{{ dataset.columns.length }}</div>
      </div>
      <div>
        <div class="text-xs text-color-secondary uppercase">Created</div>
        <div class="text-sm">{{ dataset.created_at }} <span class="text-color-secondary">by {{ dataset.created_by }}</span></div>
      </div>
    </div>

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
        :loading="loading"
        :paginator="true"
        :rows="pageSize"
        :first="first"
        :totalRecords="totalRecords"
        :rowsPerPageOptions="[10, 25, 50, 100, 250]"
        :sortField="sortField"
        :sortOrder="sortOrder"
        stripedRows
        size="small"
        scrollable
        scrollHeight="60vh"
        @page="onPage"
        @sort="onSort"
        currentPageReportTemplate="{first}–{last} of {totalRecords}"
        :paginatorTemplate="'FirstPageLink PrevPageLink CurrentPageReport NextPageLink LastPageLink RowsPerPageDropdown'"
        :alwaysShowPaginator="true"
      >
        <Column field="__idx" header="#" style="width:6rem" frozen />
        <Column
          v-for="col in orderedVisible"
          :key="col"
          :field="col"
          :header="col"
          sortable
        >
          <template #body="{ data }">
            <span class="font-mono text-xs">{{ data[col] }}</span>
          </template>
        </Column>
      </DataTable>
    </div>
  </div>
</template>
