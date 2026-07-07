<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'

// Server-driven data table shared across raw tabular-data views (dataset
// browsing, backtesting predictions, forecast/credit-risk results). Every
// page/sort/filter change round-trips through `fetchPage` — the caller owns
// the actual API call, this component only owns table state + rendering.
//
// Search/filters/sort live in a PrimeVue Toolbar above the table (not
// per-column, per design.md) and are staged: editing them doesn't fetch
// anything until "Apply" is clicked, so typing a search term or picking
// several filter values doesn't fire a request per keystroke/click. The
// "Filters" button toggles an inline filter strip (inset background, labeled
// dropdowns). A column's filter is a text "contains" input by default, or a
// searchable multi-select when it has <= categoricalThreshold distinct values
// — see resolveFilterKinds().
const props = defineProps({
  // [{ field, header, sortable=true, filterable=true, width, hidden=false,
  //    align?: 'left'|'right'|'center', mono?: boolean, formatter?(value, row) }]
  columns: { type: Array, required: true },
  // ({ page, pageSize, sortColumn, sortOrder, filters }) => Promise<AxiosResponse<{ rows, total }>>
  // matches the toPageParams()-shaped `@/api/*` wrappers — pass one directly,
  // e.g. (p) => datasetsAPI.rows(id, p)
  fetchPage: { type: Function, required: true },
  // (field) => Promise<AxiosResponse<{ values, truncated }>>
  fetchDistinct: { type: Function, default: null },
  rowKey: { type: String, default: null },
  // Optional card header shown above the toolbar (design.png style).
  title: { type: String, default: null },
  caption: { type: String, default: null }, // falls back to "<total> rows" when title is set
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

const resolvedCaption = computed(() => {
  if (props.caption) return props.caption
  if (props.title) return `${totalRecords.value.toLocaleString()} rows`
  return null
})

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

// Inline filter strip (design.png): toggled by the "Filters" toolbar button.
const showFilters = ref(false)
const hasFilterStrip = computed(() => filterableColumns.value.length > 0)
function toggleFilters() {
  showFilters.value = !showFilters.value
}

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

function bodyClass(col) {
  return [
    'cdt-cell',
    col.align === 'right' && 'cdt-cell--right',
    col.align === 'center' && 'cdt-cell--center',
    col.mono && 'cdt-cell--mono'
  ].filter(Boolean)
}

function headerClass(col) {
  return [
    col.align === 'right' && 'cdt-th--right',
    col.align === 'center' && 'cdt-th--center'
  ].filter(Boolean)
}

// ── Download: fetch up to `maxDownloadRows` rows (reflecting the currently
// APPLIED search/filters/sort, not unapplied toolbar drafts) and save as CSV.
const downloading = ref(false)

async function downloadCsv() {
  const target = Math.max(1, Math.floor(props.maxDownloadRows) || 1)
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
    <div v-if="title" class="cdt-header">
      <span class="cdt-title">{{ title }}</span>
      <span v-if="resolvedCaption" class="cdt-caption">{{ resolvedCaption }}</span>
    </div>

    <Toolbar class="cdt-toolbar">
      <template #start>
        <IconField class="cdt-search" iconPosition="left">
          <InputIcon class="pi pi-search" />
          <InputText v-model="searchDraft" placeholder="Search…" class="w-full" @keyup.enter="applyToolbar" />
        </IconField>

        <Button
          v-if="hasFilterStrip"
          :label="activeFilterCount > 0 ? `Filters (${activeFilterCount})` : 'Filters'"
          icon="pi pi-sliders-h"
          class="cdt-btn-dark"
          :class="{ 'cdt-btn-active': showFilters }"
          @click="toggleFilters"
        />

        <EySelect
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

        <Button label="Apply" class="cdt-btn-dark" @click="applyToolbar" />
        <Button label="Reset" text class="cdt-btn-reset" @click="resetToolbar" />
      </template>

      <template #end>
        <Button
          label="Download"
          icon="pi pi-download"
          class="cdt-btn-outline"
          :loading="downloading"
          @click="downloadCsv"
        />
      </template>
    </Toolbar>

    <div v-if="hasFilterStrip && showFilters" class="cdt-filter-strip">
      <div v-for="col in filterableColumns" :key="col.field" class="cdt-filter-field">
        <span class="cdt-filter-label">{{ col.header || col.field }}</span>
        <EySelect
          v-if="columnFilterKind[col.field] === 'categorical'"
          v-model="filterDrafts[col.field]"
          :options="distinctOptions[col.field]"
          :filter="true"
          :multiple="true"
          showToggleAll
          placeholder="All"
          class="cdt-filter-control"
        />
        <InputText
          v-else
          v-model="filterDrafts[col.field]"
          type="text"
          class="cdt-filter-control cdt-filter-text"
          placeholder="Contains…"
          @keyup.enter="applyToolbar"
        />
      </div>
      <div class="cdt-filter-actions">
        <Button label="Reset" text class="cdt-btn-reset" @click="resetToolbar" />
        <Button label="Apply" class="cdt-btn-dark" @click="applyToolbar" />
      </div>
    </div>

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
        <div class="cdt-empty">{{ emptyMessage }}</div>
      </template>

      <Column
        v-for="col in visibleColumns"
        :key="col.field"
        :field="col.field"
        :header="col.header"
        :sortable="false"
        :headerClass="headerClass(col)"
        :style="{ minWidth: col.width || '10rem' }"
      >
        <template #body="slotProps">
          <slot :name="`cell-${col.field}`" v-bind="slotProps">
            <span :class="bodyClass(col)">{{ cellValue(col, slotProps.data) }}</span>
          </slot>
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<style scoped>
.cdt-wrap {
  display: flex;
  flex-direction: column;
}

/* ── Card header (title + caption) ─────────────────────────────────────────── */
.cdt-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 14px;
}
.cdt-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text-color);
}
.cdt-caption {
  font-size: 12px;
  color: var(--text-color-muted-2);
}

/* ── Toolbar ───────────────────────────────────────────────────────────────── */
:deep(.cdt-toolbar.p-toolbar) {
  background: transparent;
  border: 0;
  padding: 0;
  margin-bottom: 12px;
  gap: 10px;
  flex-wrap: wrap;
}
:deep(.cdt-toolbar .p-toolbar-group-start),
:deep(.cdt-toolbar .p-toolbar-group-end) {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cdt-search {
  width: 260px;
}
:deep(.cdt-search .p-inputtext) {
  height: 40px;
  font-size: 13px;
}

.cdt-sort-drop {
  width: 150px;
}

/* Dark ink buttons (Filters, Apply) — matches the primary-button treatment. */
:deep(.cdt-btn-dark.p-button) {
  height: 40px;
  font-size: 13px;
  font-weight: 600;
}
:deep(.cdt-btn-active.p-button) {
  box-shadow: 0 0 0 2px var(--yellow);
}

:deep(.cdt-btn-reset.p-button) {
  height: 40px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-color-muted);
}
:deep(.cdt-btn-reset.p-button:hover) {
  color: var(--ink);
  background: var(--surface-hover);
}

:deep(.cdt-btn-outline.p-button) {
  height: 40px;
  font-size: 13px;
  font-weight: 600;
  background: var(--surface-card);
  border: 1px solid var(--surface-border-input);
  color: var(--text-color);
}
:deep(.cdt-btn-outline.p-button:hover) {
  background: var(--surface-hover);
  border-color: var(--ink);
  color: var(--ink);
}
:deep(.cdt-btn-outline .p-button-icon) {
  color: var(--text-color-muted);
}

/* Sort direction toggle — dark square icon button. */
:deep(.cdt-sort-toggle.p-togglebutton) {
  height: 40px;
  width: 44px;
  padding: 0;
  background: var(--button-primary-bg);
  border: 1px solid var(--button-primary-bg);
  color: #fff;
  border-radius: 2px;
}
:deep(.cdt-sort-toggle.p-togglebutton.p-highlight),
:deep(.cdt-sort-toggle.p-togglebutton:not(.p-disabled):hover) {
  background: var(--button-primary-hover);
  border-color: var(--button-primary-hover);
  color: #fff;
}
:deep(.cdt-sort-toggle .p-button-icon) {
  color: var(--yellow);
  font-size: 14px;
}
:deep(.cdt-sort-toggle.p-disabled) {
  opacity: 0.4;
}

/* ── Inline filter strip ───────────────────────────────────────────────────── */
.cdt-filter-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 16px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: var(--surface-inset);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
}
.cdt-filter-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 200px;
  min-width: 170px;
}
.cdt-filter-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--text-color-muted);
}
.cdt-filter-control {
  width: 100%;
}
:deep(.cdt-filter-text.p-inputtext) {
  height: 40px;
  font-size: 13px;
}
.cdt-filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* ── Error banner ──────────────────────────────────────────────────────────── */
.cdt-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--error-color, #c4331d);
  border-radius: 2px;
  color: var(--error-text-color, #a32b18);
  font-size: 13px;
}

/* ── Table body cells ──────────────────────────────────────────────────────── */
.cdt-cell {
  white-space: pre-wrap;
  font-size: 13px;
  color: var(--text-color);
}
.cdt-cell--right {
  display: block;
  text-align: right;
}
.cdt-cell--center {
  display: block;
  text-align: center;
}
.cdt-cell--mono {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
}

.cdt-empty {
  padding: 32px 0;
  text-align: center;
  color: var(--text-color-muted-2);
  font-size: 13px;
}

/* ── Table chrome (header rule, dividers, hover) ───────────────────────────── */
:deep(.cdt-table .p-datatable-thead > tr > th) {
  background: var(--surface-card);
  color: var(--text-color-muted);
  font-weight: 700;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  border: 0;
  border-bottom: 2px solid var(--ink);
  padding: 12px 16px;
}
:deep(.cdt-table .p-datatable-thead > tr > th.cdt-th--right .p-column-header-content) {
  justify-content: flex-end;
}
:deep(.cdt-table .p-datatable-thead > tr > th.cdt-th--center .p-column-header-content) {
  justify-content: center;
}

:deep(.cdt-table .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border-row);
  padding: 11px 16px;
}
:deep(.cdt-table .p-datatable-tbody > tr:last-child > td) {
  border-bottom: 0;
}
:deep(.cdt-table .p-datatable-tbody > tr:hover > td) {
  background: var(--surface-hover);
}

:deep(.cdt-table .p-paginator) {
  border: 0;
  border-top: 1px solid var(--surface-border-row);
  background: transparent;
  padding-top: 12px;
}
</style>
