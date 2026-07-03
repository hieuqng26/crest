<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { FilterMatchMode } from 'primevue/api'

// Server-driven data table shared across raw tabular-data views (dataset
// browsing, backtesting predictions, forecast/credit-risk results). Every
// page/sort/filter change round-trips through `fetchPage` — the caller owns
// the actual API call, this component only owns table state + rendering.
//
// Column filters: a text "contains" input by default, or a searchable
// multi-select dropdown when the column has <= categoricalThreshold distinct
// values. Distinct values come from `fetchDistinct` when given; otherwise,
// if the whole result set already fits on one page (small/detail tables that
// wrap a single full fetch), they're derived from the loaded rows instead —
// see resolveFilterKinds().
const props = defineProps({
  // [{ field, header, sortable=true, filterable=true, width, hidden=false, formatter?(value, row) }]
  columns: { type: Array, required: true },
  // ({ page, pageSize, sortColumn, sortOrder, filters }) => Promise<AxiosResponse<{ rows, total }>>
  // matches the toPageParams()-shaped `@/api/*` wrappers — pass one directly,
  // e.g. (p) => datasetsAPI.rows(id, p)
  fetchPage: { type: Function, required: true },
  // (field) => Promise<AxiosResponse<{ values, truncated }>>
  fetchDistinct: { type: Function, default: null },
  rowKey: { type: String, default: null },
  pageSizeOptions: { type: Array, default: () => [20, 50, 100, 250] },
  initialPageSize: { type: Number, default: 50 },
  categoricalThreshold: { type: Number, default: 30 },
  emptyMessage: { type: String, default: 'No data found.' },
  scrollHeight: { type: String, default: null },
  initialSortField: { type: String, default: null },
  initialSortOrder: { type: Number, default: null } // 1 | -1
})

const rows = ref([])
const totalRecords = ref(0)
const loading = ref(true)
const error = ref(null)

const page = ref(0)
const pageSize = ref(props.initialPageSize)
const sortField = ref(props.initialSortField)
const sortOrder = ref(props.initialSortField ? (props.initialSortOrder ?? 1) : null)

const visibleColumns = computed(() => props.columns.filter((c) => !c.hidden))

// PrimeVue's filterDisplay="row" needs a `filters` model shaped
// { [field]: { value, matchMode } } to know which columns have a filter row.
const filters = reactive({})
const columnFilterKind = reactive({}) // field -> 'text' | 'categorical' (unset while unresolved)
const distinctOptions = reactive({}) // field -> string[]
const filterKindsResolved = ref(false)

function syncFiltersModel() {
  for (const col of visibleColumns.value) {
    if (col.filterable === false) continue
    if (!(col.field in filters)) {
      filters[col.field] = { value: null, matchMode: FilterMatchMode.CONTAINS }
    }
  }
}
syncFiltersModel()

// Categorical columns filter by exact match against a set of values (mode
// "in", value an array) rather than the default free-text "contains".
function markCategorical(field, values) {
  distinctOptions[field] = values
  columnFilterKind[field] = 'categorical'
  if (filters[field]) {
    filters[field].matchMode = FilterMatchMode.IN
    filters[field].value = []
  }
}

async function resolveFilterKinds() {
  const pending = visibleColumns.value.filter(
    (c) => c.filterable !== false && !columnFilterKind[c.field]
  )
  await Promise.all(
    pending.map(async (col) => {
      if (props.fetchDistinct) {
        try {
          const { data } = await props.fetchDistinct(col.field)
          if (!data.truncated && data.values?.length) {
            markCategorical(col.field, data.values)
          } else {
            columnFilterKind[col.field] = 'text'
          }
        } catch {
          columnFilterKind[col.field] = 'text'
        }
        return
      }
      // No distinct-value source: only safe to derive locally when the
      // entire result set is already loaded (single-page "small table" case).
      if (totalRecords.value > 0 && totalRecords.value <= rows.value.length) {
        const unique = [...new Set(rows.value.map((r) => r[col.field]))]
          .filter((v) => v !== null && v !== undefined && v !== '')
          .map(String)
          .sort()
        if (unique.length > 0 && unique.length <= props.categoricalThreshold) {
          markCategorical(col.field, unique)
          return
        }
      }
      columnFilterKind[col.field] = 'text'
    })
  )
}

function buildFilterPayload() {
  const out = {}
  for (const [field, model] of Object.entries(filters)) {
    const v = model.value
    if (v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)) {
      continue
    }
    out[field] = { mode: model.matchMode === FilterMatchMode.IN ? 'in' : 'contains', value: v }
  }
  return out
}

async function loadPage() {
  loading.value = true
  error.value = null
  try {
    const { data } = await props.fetchPage({
      page: page.value,
      pageSize: pageSize.value,
      sortColumn: sortField.value,
      sortOrder: sortOrder.value === 1 ? 'asc' : sortOrder.value === -1 ? 'desc' : null,
      filters: buildFilterPayload()
    })
    rows.value = data.rows ?? []
    totalRecords.value = data.total ?? rows.value.length
  } catch (e) {
    error.value = e?.response?.data?.error ?? e.message ?? 'Failed to load data'
    rows.value = []
    totalRecords.value = 0
  } finally {
    loading.value = false
    if (!filterKindsResolved.value) {
      filterKindsResolved.value = true
      resolveFilterKinds()
    }
  }
}

function onPage(e) {
  page.value = e.page
  pageSize.value = e.rows
  loadPage()
}

function onSort(e) {
  sortField.value = e.sortField ?? null
  sortOrder.value = e.sortOrder || null
  page.value = 0
  loadPage()
}

function onFilter() {
  page.value = 0
  loadPage()
}

// Text filters shouldn't fire a request per keystroke.
const debounceTimers = {}
function debouncedFilter(field, filterCallback) {
  clearTimeout(debounceTimers[field])
  debounceTimers[field] = setTimeout(filterCallback, 300)
}

function cellValue(col, data) {
  const raw = data[col.field]
  if (col.formatter) return col.formatter(raw, data)
  return raw === null || raw === undefined || raw === '' ? '—' : raw
}

watch(
  () => props.columns,
  () => {
    syncFiltersModel()
    resolveFilterKinds()
  }
)

defineExpose({ refresh: loadPage, rows, totalRecords })
onMounted(loadPage)
</script>

<template>
  <div class="cdt-wrap">
    <div v-if="error" class="cdt-error">
      <i class="pi pi-exclamation-triangle" />
      <span>{{ error }}</span>
    </div>

    <DataTable
      :value="rows"
      :dataKey="rowKey"
      lazy
      :loading="loading"
      :totalRecords="totalRecords"
      paginator
      :rows="pageSize"
      :first="page * pageSize"
      :rowsPerPageOptions="pageSizeOptions"
      :sortField="sortField"
      :sortOrder="sortOrder"
      removableSort
      filterDisplay="row"
      v-model:filters="filters"
      size="small"
      class="cdt-table"
      :scrollable="!!scrollHeight"
      :scrollHeight="scrollHeight"
      currentPageReportTemplate="{first}–{last} of {totalRecords}"
      paginatorTemplate="FirstPageLink PrevPageLink CurrentPageReport NextPageLink LastPageLink RowsPerPageDropdown"
      :alwaysShowPaginator="totalRecords > 0"
      @page="onPage"
      @sort="onSort"
      @filter="onFilter"
    >
      <template #empty>
        <div class="text-center py-5 text-color-secondary text-sm">{{ emptyMessage }}</div>
      </template>

      <Column
        v-for="col in visibleColumns"
        :key="col.field"
        :field="col.field"
        :header="col.header"
        :sortable="col.sortable !== false"
        :filterField="col.field"
        :showFilterMenu="false"
        :style="{ minWidth: col.width || '10rem' }"
      >
        <template #body="slotProps">
          <slot :name="`cell-${col.field}`" v-bind="slotProps">
            <span class="cdt-cell">{{ cellValue(col, slotProps.data) }}</span>
          </slot>
        </template>

        <template v-if="col.filterable !== false" #filter="{ filterModel, filterCallback }">
          <MultiSelect
            v-if="columnFilterKind[col.field] === 'categorical'"
            v-model="filterModel.value"
            :options="distinctOptions[col.field]"
            filter
            placeholder="Any"
            display="chip"
            class="cdt-filter-multiselect"
            @change="filterCallback()"
          />
          <InputText
            v-else
            v-model="filterModel.value"
            type="text"
            class="cdt-filter-text p-column-filter"
            placeholder="Search"
            @input="debouncedFilter(col.field, filterCallback)"
          />
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<style scoped>
.cdt-error {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.9rem;
  margin-bottom: 0.75rem;
  border: 1px solid #f87171;
  border-radius: var(--radius-md, 8px);
  color: #f87171;
  font-size: 0.82rem;
}

.cdt-cell {
  white-space: pre-wrap;
  font-size: 0.82rem;
}

.cdt-filter-text,
.cdt-filter-multiselect {
  width: 100%;
  height: 2rem;
  font-size: 0.78rem;
}

:deep(.cdt-filter-multiselect .p-multiselect-label) {
  padding: 0.3rem 0.5rem;
  font-size: 0.78rem;
}

:deep(.cdt-table .p-datatable-thead > tr:first-child > th) {
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-weight: 500;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.6rem 0.85rem;
}

:deep(.cdt-table .p-datatable-thead > tr:last-child > th) {
  background: var(--surface-card);
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.4rem 0.6rem;
}

:deep(.cdt-table .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.6rem 0.85rem;
}

:deep(.cdt-table .p-datatable-tbody > tr:last-child > td) {
  border-bottom: 0;
}

:deep(.cdt-table .p-datatable-tbody > tr:hover > td) {
  background: var(--surface-hover, rgba(255, 255, 255, 0.03));
}

:deep(.cdt-table .p-paginator) {
  border: 0;
  border-top: 1px solid var(--surface-border);
  background: transparent;
}
</style>
