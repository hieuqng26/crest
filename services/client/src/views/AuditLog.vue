<template>
  <div>
    <PageHeader eyebrow="SYSTEM" title="Audit Logs" subtitle="Search and export system activity records." />

    <!-- Filters panel -->
    <div class="panel panel--emphasis mb-4">
      <div class="panel-section-label mb-3">Search Criteria</div>

      <div class="grid-filters mb-4">
        <div class="filter-field">
          <label class="field-label">Date From</label>
          <Calendar v-model="dateFrom" showIcon iconDisplay="input" class="w-full" />
        </div>
        <div class="filter-field">
          <label class="field-label">Date To</label>
          <Calendar v-model="dateTo" showIcon iconDisplay="input" class="w-full" />
        </div>
        <div class="filter-field">
          <label class="field-label">User ID</label>
          <InputText v-model="userEmailInput" class="w-full" />
        </div>
        <div class="filter-field">
          <label class="field-label">Module</label>
          <EySelect
            v-model="selectedModules"
            :loading="loadingDD"
            :options="moduleOptions"
            :filter="moduleOptions.length >= 5"
            placeholder="All"
            :multiple="true"
            showToggleAll
            class="w-full"
          />
        </div>
        <div class="filter-field">
          <label class="field-label">Sub-module</label>
          <EySelect
            v-model="selectedSubmodules"
            :loading="loadingDD"
            :options="submoduleOptions"
            :filter="submoduleOptions.length >= 5"
            placeholder="All"
            :multiple="true"
            showToggleAll
            class="w-full"
          />
        </div>
        <div class="filter-field">
          <label class="field-label">Action</label>
          <EySelect
            v-model="selectedActions"
            :loading="loadingDD"
            :options="actionOptions"
            :filter="actionOptions.length >= 5"
            placeholder="All"
            :multiple="true"
            showToggleAll
            class="w-full"
          />
        </div>
      </div>

      <div class="crit-actions">
        <Button label="Apply filters" class="btn-apply" @click="onConfirmSelect" />
        <Button label="Reset" class="btn-reset" @click="onResetFilters" />
      </div>
    </div>

    <!-- Results panel -->
    <div class="panel">
      <Skeleton v-if="loadingTable" width="100%" height="150px" />

      <template v-else-if="filteredLogs.length">
        <div class="bare-table">
          <DataTable
            ref="dt"
            v-model:expandedRows="expandedRows"
            :value="filteredLogs"
            dataKey="log_id"
            lazy
            :sortField="sortColumn || 'timestamp'"
            :sortOrder="sortOrder === 'asc' ? 1 : -1"
            :rowHover="true"
            class="bare-table-inner"
            @sort="onSort"
          >
            <template #header>
              <div class="flex align-items-center justify-content-between pb-2">
                <span class="text-xs text-color-secondary">
                  Showing {{ currentPage * pageSize + 1 }}–{{ currentPage * pageSize + filteredLogs.length }} of {{ totalSize }} entries
                </span>
                <Button
                  icon="pi pi-download"
                  label="Export"
                  size="small"
                  text
                  class="export-btn"
                  @click="exportMenu.toggle($event)"
                />
                <Menu ref="exportMenu" :model="downloadOptions" popup />
              </div>
            </template>

            <Column expander style="width: 40px" />
            <Column field="timestamp"    header="Last Update"  :sortable="true" style="min-width: 168px">
              <template #body="{ data }"><span class="font-mono cell-mono">{{ formatDate(data.timestamp, true) }}</span></template>
            </Column>
            <Column field="user_email"   header="User ID"      :sortable="true" style="min-width: 140px" />
            <Column field="role"         header="Role"         :sortable="true" style="min-width: 96px" />
            <Column field="action"       header="Action"       :sortable="true" style="min-width: 100px" />
            <Column field="module"       header="Module"       :sortable="true" style="min-width: 96px" />
            <Column field="submodule"    header="Submodule"    :sortable="true" style="min-width: 104px" />
            <Column field="status"       header="Status"       :sortable="true" style="min-width: 96px">
              <template #body="{ data }">
                <Tag :value="data.status" :severity="getStatusLabel(data.status)" />
              </template>
            </Column>
            <Column field="log_id"       header="Identifier"   :sortable="true" style="min-width: 120px">
              <template #body="{ data }">
                <span class="font-mono cell-mono" :title="data.log_id">{{ shortId(data.log_id) }}</span>
              </template>
            </Column>
            <Column field="description"  header="Description"  :sortable="true" style="min-width: 220px" />

            <!-- Everything else (IPs, device, session, login meta, API detail)
                 lives in the expansion so the scan surface stays 9 columns. -->
            <template #expansion="{ data }">
              <div class="log-detail-grid">
                <div v-for="f in DETAIL_FIELDS" :key="f.field" class="log-detail-item">
                  <span class="log-detail-label">{{ f.label }}</span>
                  <span class="font-mono log-detail-value">{{ f.fmt ? f.fmt(data[f.field]) : (data[f.field] ?? '—') || '—' }}</span>
                </div>
              </div>
            </template>
          </DataTable>
        </div>

        <div class="flex justify-content-between align-items-center mt-4 pt-3" style="border-top: 1px solid var(--surface-border)">
          <span class="text-xs text-color-secondary">
            Showing {{ currentPage * pageSize + 1 }}–{{ currentPage * pageSize + filteredLogs.length }} of {{ totalSize }}
          </span>
          <div class="flex align-items-center gap-2">
            <span class="text-xs text-color-secondary">Rows per page</span>
            <EySelect v-model="selectedPerPage" :options="[20, 50, 80, 100]" style="width: 7rem" />
            <Paginator
              :totalRecords="totalSize"
              :perPage="pageSize"
              :currentPage="currentPage"
              @update:currentPage="onPage"
            />
          </div>
        </div>
      </template>

      <EmptyState v-else-if="!loadingTable" icon="pi pi-list">No logs found. Adjust filters and apply.</EmptyState>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useStore } from 'vuex'
import { useToast } from 'primevue/usetoast'
import { saveFile } from '@/views/composables/views.js'
import { formatDate } from '@/utils'
import Paginator from '@/components/Paginator.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const store = useStore()
const toast = useToast()

// constants
const COLUMN_MAP = {
  'Last Update': 'timestamp',
  'User ID': 'user_email',
  Role: 'role',
  Action: 'action',
  Identifier: 'log_id',
  Module: 'module',
  Submodule: 'submodule',
  Status: 'status',
  'IP Address': 'ip_address',
  Description: 'description',
  'Device Info': 'device_info',
  'Session ID': 'session_id',
  'Last Login': 'login_time',
  'Last Logout': 'logout_time',
  'Login Type': 'login_type',
  'API Endpoint': 'api_endpoints',
  'Database Involved': 'database_involved',
  'Application Version': 'application_version',
  'Error Code': 'error_codes',
  JobID: 'job_id',
  ApproverRejector: 'job_judged_by'
}

// refs
const dt = ref()
const expandedRows = ref([])
const shortId = (id) => (id && id.length > 12 ? id.slice(0, 8) + '…' : (id ?? '—'))

// Long-tail fields shown only in the row expansion (export still includes all
// of them via COLUMN_MAP).
const DETAIL_FIELDS = [
  { field: 'log_id', label: 'Identifier' },
  { field: 'ip_address', label: 'IP Address' },
  { field: 'session_id', label: 'Session ID' },
  { field: 'device_info', label: 'Device Info' },
  { field: 'login_time', label: 'Last Login', fmt: (v) => formatDate(v, true) },
  { field: 'logout_time', label: 'Last Logout', fmt: (v) => formatDate(v, true) },
  { field: 'login_type', label: 'Login Type' },
  { field: 'api_endpoints', label: 'API Endpoint' },
  { field: 'database_involved', label: 'Database Involved' },
  { field: 'application_version', label: 'App Version' },
  { field: 'error_codes', label: 'Error Code' },
  { field: 'job_id', label: 'Job ID' },
  { field: 'job_judged_by', label: 'Approver/Rejector' },
]
const exportMenu = ref()
const logs = ref([])
const filteredLogs = ref([])

const dateFrom = ref(null)
const dateTo = ref(null)
const userEmailInput = ref('')
const moduleOptions = ref([])
const selectedModules = ref([])
const submoduleOptions = ref([])
const selectedSubmodules = ref([])
const submoduleDictionaries = ref([])
const actionOptions = ref([])
const selectedActions = ref([])
const loadingTable = ref(false)
const loadingDD = ref(false)

const currentPage = ref(0)
const totalSize = ref(0)
const pageSize = ref(20)
const selectedPerPage = ref(20)

// search — sortColumn/sortOrder are set from the results table's header clicks
const sortColumn = ref(null)
const sortOrder = ref('asc')

// properties
onMounted(async () => {
  loadingDD.value = true
  // get available moduleOptions, actionOptions
  await store
    .dispatch('getAllLogs', {
      columns: ['action', 'module', 'submodule'].join('\x1e')
    })
    .then((res) => {
      if (!res?.data) return
      const data = res.data

      moduleOptions.value = Array.from(
        new Set(data.map((log) => log.module))
      ).filter((module) => module)
      actionOptions.value = Array.from(
        new Set(data.map((log) => log.action))
      ).filter((action) => action)
      submoduleDictionaries.value = data.reduce((row, columns) => {
        const { module, submodule } = columns
        if (!row[module]) {
          row[module] = ['']
        }
        row[module].push(submodule)
        return row
      }, {})
    })
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'Failed to get logs data. ' + msg,
        life: 5000
      })
    })
    .finally(() => {
      loadingDD.value = false
    })

  await loadData(
    currentPage.value,
    pageSize.value,
    dateFrom.value,
    dateTo.value,
    userEmailInput.value,
    selectedModules.value,
    selectedSubmodules.value,
    selectedActions.value
  )
})

const onConfirmSelect = () => {
  loadData(
    0,
    pageSize.value,
    dateFrom.value,
    dateTo.value,
    userEmailInput.value,
    selectedModules.value,
    selectedSubmodules.value,
    selectedActions.value,
    sortColumn.value,
    sortOrder.value
  )
}

// Sorting is driven by the results table's column headers (server-side),
// replacing the old Sort By control in the criteria panel.
const onSort = (e) => {
  sortColumn.value = e.sortField || null
  sortOrder.value = e.sortOrder === 1 ? 'asc' : 'desc'
  onConfirmSelect()
}

const onResetFilters = () => {
  dateFrom.value = null
  dateTo.value = null
  userEmailInput.value = ''
  selectedModules.value = []
  selectedSubmodules.value = []
  selectedActions.value = []
  sortColumn.value = null
  sortOrder.value = 'asc'
  onConfirmSelect()
}

watch([currentPage, pageSize], ([p, p_size]) => {
  loadPage(
    p,
    p_size,
    dateFrom.value,
    dateTo.value,
    userEmailInput.value,
    selectedModules.value,
    selectedSubmodules.value,
    selectedActions.value,
    sortColumn.value,
    sortOrder.value
  )
})

watch([selectedModules, submoduleDictionaries], ([modules, submoduleDict]) => {
  if (modules && submoduleDict) {
    submoduleOptions.value = Array.from(
      new Set(modules.flatMap((module) => submoduleDict[module] || []))
    ).filter((submodule) => submodule)
    if (submoduleOptions.value.length == 0) {
      selectedSubmodules.value = []
    }
  }
})

// Pagination logics
const loadData = async (
  page,
  page_size,
  date_from,
  date_to,
  user_id,
  module,
  submodule,
  action,
  sort_column,
  sort_order
) => {
  currentPage.value = 0

  await store
    .dispatch('getAllLogs', {
      date_from: date_from,
      date_to: date_to,
      user_id: user_id,
      module: module.join('\x1e'),
      submodule: submodule.join('\x1e'),
      action: action.join('\x1e'),
      get_size: true,
      sort_column: sort_column,
      sort_order: sort_order
    })
    .then((res) => {
      totalSize.value = res.data
    })
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'Failed to load logs. ' + msg,
        life: 5000
      })
    })

  loadPage(
    page,
    page_size,
    date_from,
    date_to,
    user_id,
    module,
    submodule,
    action,
    sort_column,
    sort_order
  )
}

const loadPage = async (
  page,
  page_size,
  date_from,
  date_to,
  user_id,
  module,
  submodule,
  action,
  sort_column,
  sort_order
) => {
  loadingTable.value = true
  await store
    .dispatch('getAllLogs', {
      page: page,
      page_size: page_size,
      date_from: date_from,
      date_to: date_to,
      user_id: user_id,
      module: module.join('\x1e'),
      submodule: submodule.join('\x1e'),
      action: action.join('\x1e'),
      sort_column: sort_column,
      sort_order: sort_order
    })
    .then((res) => {
      if (res?.data) {
        logs.value = res.data
        filteredLogs.value = logs.value

        // convert timestamp to date object to sort
        filteredLogs.value.forEach((d) => {
          d.timestamp = toDate(d.timestamp)
          d.login_time = toDate(d.login_time)
          d.logout_time = toDate(d.logout_time)
        })
      }
    })
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'Failed to load logs. ' + msg,
        life: 5000
      })
    })
    .finally(() => {
      loadingTable.value = false
    })
}

const onPage = (page) => {
  currentPage.value = page
}

watch(selectedPerPage, async (p) => {
  pageSize.value = p
  currentPage.value = 0
})

const getStatusLabel = (status) => {
  switch (status) {
    case 'success':
      return 'success'

    case 'failed':
      return 'danger'

    default:
      return null
  }
}

const downloadOptions = [
  {
    label: 'csv',
    icon: 'fi fi-rr-file-csv',
    command: () => {
      const data = preprocessDownloadData(
        JSON.parse(JSON.stringify(dt.value.processedData))
      )
      saveFile(data, 'csv', 'auditlog')
    }
  },
  {
    label: 'xlsx',
    icon: 'fi fi-rr-file-excel',
    command: () => {
      const data = preprocessDownloadData(
        JSON.parse(JSON.stringify(dt.value.processedData))
      )
      saveFile(data, 'xlsx', 'auditlog')
    }
  }
]

const preprocessDownloadData = (data) => {
  const outputFields = Object.values(COLUMN_MAP)
  const outputFieldsDisplayed = Object.keys(COLUMN_MAP)

  data.forEach((item) => {
    item.timestamp = formatDate(item.timestamp, true)
    item.login_time = formatDate(item.login_time, true)
    item.logout_time = formatDate(item.logout_time, true)
  })

  // arrange fields with the order of outputFields, rename as outputFieldsDisplayed
  const dataArranged = data.map((obj) => {
    const arrangedObj = {}
    for (var i = 0; i < outputFields.length; i++) {
      const field = outputFields[i]
      if (Object.hasOwn(obj, field)) {
        const field_displayed = outputFieldsDisplayed[i]
        arrangedObj[field_displayed] = obj[field]
      }
    }
    return arrangedObj
  })

  return dataArranged
}

const toDate = (date) => {
  return date ? new Date(date) : null
}
</script>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 1.25rem;
}
.panel-section-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

.grid-filters {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}
.filter-field { display: flex; flex-direction: column; gap: 0.4rem; }
.field-label  { font-size: 0.75rem; font-weight: 500; color: var(--text-color-secondary); }

.export-btn { color: var(--text-color-secondary) !important; font-size: 0.8rem; }
.export-btn:hover { color: var(--text-color) !important; background: var(--surface-hover) !important; }

/* Emphasis card — 3px ink top border (design.md). */
.panel--emphasis { border-top: 3px solid var(--ink); }

.crit-actions { display: flex; gap: 10px; }
:deep(.btn-apply.p-button) {
  height: 36px;
  background: var(--ink);
  border: 1px solid var(--ink);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
:deep(.btn-apply.p-button:hover) { background: var(--ink-3); border-color: var(--ink-3); }
:deep(.btn-reset.p-button) {
  height: 36px;
  background: var(--surface-card);
  border: 1px solid var(--surface-border-input);
  color: var(--text-color-secondary);
  font-size: 13px;
  font-weight: 600;
}
:deep(.btn-reset.p-button:hover) { border-color: var(--ink); color: var(--ink); }

.bare-table { margin: 0 -1.25rem; }
/* Table chrome comes from the global _brand.scss skin. */
:deep(.bare-table-inner .p-datatable-header) {
  background: transparent;
  border: 0;
  padding: 0 1.25rem 0.75rem;
}
.cell-mono { font-size: 12px; }

.log-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px 24px;
  padding: 14px 20px;
  background: var(--surface-inset);
}
.log-detail-item { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.log-detail-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-color-muted);
}
.log-detail-value { font-size: 12px; word-break: break-all; }
</style>
