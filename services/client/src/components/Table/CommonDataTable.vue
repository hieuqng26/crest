<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'

// Server-driven data table shared across raw tabular-data views (dataset
// browsing, backtesting predictions, forecast/credit-risk results). Every
// page/sort/filter change round-trips through `fetchPage` — the caller owns
// the actual API call, this component only owns table state + rendering.
//
// Search/filters/sort live in a toolbar above the table (not per-column, per
// design.md) and are staged: editing them doesn't fetch anything until
// "Apply" is clicked, so typing a search term or picking several filter
// values doesn't fire a request per keystroke/click. Column filters are a
// text "contains" input by default, or a searchable multi-select when the
// column has <= categoricalThreshold distinct values — see resolveFilterKinds().
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
  initialSortOrder: { type: Number, default: null }, // 1 | -1
  downloadFilename: { type: String, default: 'export' },
  maxDownloadRows: { type: Number, default: 20000 },
  externalFilters: { type: Object, default: () => ({}) }
})

const GLOBAL_SEARCH_KEY = '__search__'

const rows = ref([])
const totalRecords = ref(0)
const loading = ref(true)
const error = ref(null)

const page = ref(0)
const pageSize = ref(props.initialPageSize)

// ── Applied state (drives fetchPage) vs. draft state (bound to the toolbar,
// only takes effect on "Apply") ──────────────────────────────────────────────
const sortField = ref(props.initialSortField)
const sortOrder = ref(props.initialSortField ? (props.initialSortOrder ?? 1) : null)
const appliedSearch = ref('')
const appliedFilters = reactive({}) // field -> { mode, value }

const sortFieldDraft = ref(sortField.value)
const sortDescDraft = ref(sortOrder.value === -1) // ToggleButton needs a boolean, not 1/-1
const searchDraft = ref('')
const filterDrafts = reactive({}) // field -> string | string[]

const visibleColumns = computed(() => props.columns.filter((c) => !c.hidden))
const filterableColumns = computed(() => visibleColumns.value.filter((c) => c.filterable !== false))
const sortableColumns = computed(() => visibleColumns.value.filter((c) => c.sortable !== false))
const sortOptions = computed(() => sortableColumns.value.map((c) => ({ label: c.header || c.field, value: c.field })))

function syncFilterDrafts() {
  for (const col of filterableColumns.value) {
    if (!(col.field in filterDrafts)) filterDrafts[col.field] = null
  }
}
syncFilterDrafts()

const activeFilterCount = computed(
  () => Object.values(filterDrafts).filter((v) => v !== null && v !== '' && !(Array.isArray(v) && v.length === 0)).length
)

// field -> 'text' | 'categorical' (unset while unresolved)
const columnFilterKind = reactive({})
const distinctOptions = reactive({}) // field -> string[]
const filterKindsResolved = ref(false)

function markCategorical(field, values) {
  distinctOptions[field] = values
  columnFilterKind[field] = 'categorical'
}

async function resolveFilterKinds() {
  const pending = filterableColumns.value.filter((c) => !columnFilterKind[c.field])
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

function buildFilterPayload(filters, search) {
  const out = {}
  for (const [field, value] of Object.entries(filters)) {
    if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) {
      continue
    }
    out[field] = { mode: Array.isArray(value) ? 'in' : 'contains', value }
  }
  if (search && search.trim()) {
    out[GLOBAL_SEARCH_KEY] = { value: search.trim() }
  }
  Object.assign(out, props.externalFilters)
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
      filters: buildFilterPayload(appliedFilters, appliedSearch.value)
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

const filtersPanel = ref(null)
const toggleFiltersPanel = (e) => filtersPanel.value.toggle(e)

function applyToolbar() {
  sortField.value = sortFieldDraft.value
  sortOrder.value = sortFieldDraft.value ? (sortDescDraft.value ? -1 : 1) : null
  appliedSearch.value = searchDraft.value
  Object.keys(appliedFilters).forEach((k) => delete appliedFilters[k])
  Object.assign(appliedFilters, filterDrafts)
  page.value = 0
  loadPage()
}

function resetToolbar() {
  searchDraft.value = ''
  sortFieldDraft.value = null
  sortDescDraft.value = false
  for (const field of Object.keys(filterDrafts)) filterDrafts[field] = null
  applyToolbar()
}

function cellValue(col, data) {
  const raw = data[col.field]
  if (col.formatter) return col.formatter(raw, data)
  return raw === null || raw === undefined || raw === '' ? '—' : raw
}

// ── Download: fetch up to `downloadRowCount` rows (reflecting the currently
// APPLIED search/filters/sort, not unapplied toolbar drafts) and save as CSV.
const downloadRowCount = ref(100)
const downloading = ref(false)

async function downloadCsv() {
  const target = Math.max(1, Math.min(props.maxDownloadRows, Math.floor(downloadRowCount.value) || 1))
  downloading.value = true
  try {
    const collected = []
    const batchSize = 500
    let batchPage = 0
    while (collected.length < target) {
      const { data } = await props.fetchPage({
        page: batchPage,
        pageSize: Math.min(batchSize, target - collected.length),
        sortColumn: sortField.value,
        sortOrder: sortOrder.value === 1 ? 'asc' : sortOrder.value === -1 ? 'desc' : null,
        filters: buildFilterPayload(appliedFilters, appliedSearch.value)
      })
      const batchRows = data.rows ?? []
      collected.push(...batchRows)
      if (batchRows.length < batchSize || collected.length >= (data.total ?? 0)) break
      batchPage += 1
    }

    const cols = visibleColumns.value
    const header = cols.map((c) => c.header || c.field).join(',')
    const body = collected
      .map((r) => cols.map((c) => JSON.stringify(r[c.field] ?? '')).join(','))
      .join('\n')
    const blob = new Blob([header + '\n' + body], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${props.downloadFilename}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } finally {
    downloading.value = false
  }
}

watch(
  () => props.columns,
  () => {
    syncFilterDrafts()
    resolveFilterKinds()
  }
)

watch(() => props.externalFilters, () => { page.value = 0; loadPage() }, { deep: true })

defineExpose({ refresh: loadPage, rows, totalRecords })
onMounted(loadPage)
</script>

<template>
  <div class="cdt-wrap">
    <div class="cdt-toolbar">
      <IconField class="cdt-search" iconPosition="left">
        <InputIcon class="pi pi-search" />
        <InputText v-model="searchDraft" placeholder="Search…" class="w-full" @keyup.enter="applyToolbar" />
      </IconField>

      <Button
        :label="activeFilterCount > 0 ? `Filters (${activeFilterCount})` : 'Filters'"
        icon="pi pi-sliders-h"
        severity="secondary"
        outlined
        size="small"
        @click="toggleFiltersPanel"
      />

      <Dropdown
        v-model="sortFieldDraft"
        :options="sortOptions"
        optionLabel="label"
        optionValue="value"
        placeholder="Sort by…"
        showClear
        class="cdt-sort-drop"
      />
      <ToggleButton
        v-model="sortDescDraft"
        onLabel=""
        offLabel=""
        onIcon="pi pi-sort-amount-down"
        offIcon="pi pi-sort-amount-up"
        :disabled="!sortFieldDraft"
        v-tooltip.top="sortDescDraft ? 'Descending' : 'Ascending'"
        class="cdt-sort-toggle"
      />

      <Button label="Apply" size="small" @click="applyToolbar" />
      <Button label="Reset" text size="small" severity="secondary" @click="resetToolbar" />

      <div class="cdt-toolbar-spacer" />

      <div class="cdt-download">
        <InputNumber v-model="downloadRowCount" :min="1" :max="maxDownloadRows" showButtons class="cdt-download-input" inputClass="cdt-download-input-field" />
        <Button label="Download" icon="pi pi-download" size="small" severity="secondary" outlined :loading="downloading" @click="downloadCsv" />
      </div>
    </div>

    <OverlayPanel ref="filtersPanel" class="cdt-filters-panel">
      <div class="cdt-filters-panel-inner">
        <div v-for="col in filterableColumns" :key="col.field" class="cdt-filter-row">
          <div class="cdt-filter-row-label">{{ col.header || col.field }}</div>
          <MultiSelect
            v-if="columnFilterKind[col.field] === 'categorical'"
            v-model="filterDrafts[col.field]"
            :options="distinctOptions[col.field]"
            filter
            placeholder="Any value"
            display="chip"
            class="cdt-filter-multiselect"
          />
          <InputText
            v-else
            v-model="filterDrafts[col.field]"
            type="text"
            class="cdt-filter-text"
            placeholder="Contains…"
            @keyup.enter="applyToolbar"
          />
        </div>
        <div v-if="!filterableColumns.length" class="text-xs text-color-secondary">No filterable columns.</div>
        <div class="cdt-filters-panel-actions">
          <Button label="Reset" text size="small" severity="secondary" @click="resetToolbar" />
          <Button label="Apply" size="small" @click="applyToolbar(); filtersPanel.hide()" />
        </div>
      </div>
    </OverlayPanel>

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
      size="small"
      class="cdt-table"
      :scrollable="!!scrollHeight"
      :scrollHeight="scrollHeight"
      currentPageReportTemplate="{first}–{last} of {totalRecords}"
      paginatorTemplate="FirstPageLink PrevPageLink CurrentPageReport NextPageLink LastPageLink RowsPerPageDropdown"
      :alwaysShowPaginator="totalRecords > 0"
      @page="onPage"
    >
      <template #empty>
        <div class="text-center py-5 text-color-secondary text-sm">{{ emptyMessage }}</div>
      </template>

      <Column
        v-for="col in visibleColumns"
        :key="col.field"
        :field="col.field"
        :header="col.header"
        :sortable="false"
        :style="{ minWidth: col.width || '10rem' }"
      >
        <template #body="slotProps">
          <slot :name="`cell-${col.field}`" v-bind="slotProps">
            <span class="cdt-cell">{{ cellValue(col, slotProps.data) }}</span>
          </slot>
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<style scoped>
.cdt-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.85rem;
}

.cdt-search {
  width: 16rem;
}

.cdt-sort-drop {
  width: 11rem;
}
:deep(.cdt-sort-drop .p-dropdown-label) {
  font-size: 0.82rem;
}

.cdt-sort-toggle {
  height: 2.35rem;
  width: 2.35rem;
  padding: 0;
}

.cdt-toolbar-spacer {
  flex: 1 1 auto;
}

.cdt-download {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding-left: 0.75rem;
  border-left: 1px solid var(--surface-border);
}

.cdt-download-input {
  width: 6.5rem;
}
:deep(.cdt-download-input-field) {
  width: 100%;
  font-size: 0.82rem;
  padding: 0.4rem 0.5rem;
}

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

:deep(.cdt-table .p-datatable-thead > tr > th) {
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

<!--
  Unscoped: the OverlayPanel's content is teleported out of this component's
  DOM subtree via <Portal>, so scoped/:deep() selectors can't reach it —
  there's no scoped ancestor left in the actual DOM tree once teleported.
  `.cdt-filters-panel`/`.cdt-filter-*` are component-specific classes, so this
  stays safely scoped in practice despite not being Vue-scoped.
-->
<style>
.cdt-filters-panel {
  max-width: 22rem;
}
.cdt-filters-panel .p-overlaypanel-content {
  padding: 0.9rem;
}
.cdt-filters-panel-inner {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  max-height: 60vh;
  overflow-y: auto;
}
.cdt-filter-row {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.cdt-filter-row-label {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-color-secondary);
}
.cdt-filter-text,
.cdt-filter-multiselect {
  width: 100%;
  height: 2.15rem;
  font-size: 0.82rem;
  border: 1px solid var(--surface-border);
  background: var(--surface-ground);
  border-radius: var(--radius-sm, 6px);
  box-shadow: none;
}
.cdt-filter-text:focus,
.cdt-filter-multiselect.p-focus {
  background: var(--surface-card);
  border-color: var(--primary-color);
  box-shadow: none;
}
.cdt-filter-multiselect .p-multiselect-label {
  padding: 0.35rem 0.6rem;
  font-size: 0.82rem;
  color: var(--text-color);
}
.cdt-filter-multiselect .p-multiselect-label.p-placeholder {
  color: var(--text-color-secondary);
}
.cdt-filter-multiselect .p-multiselect-trigger {
  width: 1.75rem;
  color: var(--text-color-secondary);
}
.cdt-filter-multiselect .p-multiselect-token {
  padding: 0.05rem 0.45rem;
  font-size: 0.72rem;
  background: var(--surface-200, var(--surface-border));
  border-radius: 999px;
}
.cdt-filters-panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-top: 0.2rem;
  padding-top: 0.6rem;
  border-top: 1px solid var(--surface-border);
}
</style>
