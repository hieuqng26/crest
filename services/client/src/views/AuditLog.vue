<template>
  <div>
    <PageHeader eyebrow="SYSTEM" title="Audit Logs" subtitle="Search and export system activity records." />

    <!-- Filters panel -->
    <div class="panel mb-4">
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
          <MultiSelect
            v-model="selectedModules"
            :loading="loadingDD"
            :options="moduleOptions"
            :filter="moduleOptions.length >= 5"
            placeholder="All"
            :maxSelectedLabels="3"
            class="w-full"
          />
        </div>
        <div class="filter-field">
          <label class="field-label">Sub-Module</label>
          <MultiSelect
            v-model="selectedSubmodules"
            :loading="loadingDD"
            :options="submoduleOptions"
            :filter="submoduleOptions.length >= 5"
            placeholder="All"
            :maxSelectedLabels="3"
            class="w-full"
          />
        </div>
        <div class="filter-field">
          <label class="field-label">Action</label>
          <MultiSelect
            v-model="selectedActions"
            :loading="loadingDD"
            :options="actionOptions"
            :filter="actionOptions.length >= 5"
            placeholder="All"
            :maxSelectedLabels="3"
            class="w-full"
          />
        </div>
      </div>

      <div class="flex align-items-end gap-3">
        <div class="filter-field" style="min-width: 16rem">
          <label class="field-label">Sort By</label>
          <div class="flex align-items-center gap-2">
            <Dropdown
              v-model="selectedSortColumn"
              :options="searchColumns"
              :loading="loadingTable && searchColumns.length === 0"
              :filter="true"
              showClear
              class="flex-1"
            />
            <button
              class="sort-dir-btn"
              :title="selectedSortOrder ? 'Ascending' : 'Descending'"
              @click="selectedSortOrder = !selectedSortOrder"
            >
              <i :class="selectedSortOrder ? 'pi pi-sort-amount-up' : 'pi pi-sort-amount-down'" />
            </button>
          </div>
        </div>
        <Button label="Apply filters" icon="pi pi-filter" severity="secondary" outlined @click="onConfirmSelect" />
      </div>
    </div>

    <!-- Results panel -->
    <div class="panel">
      <Skeleton v-if="loadingTable" width="100%" height="150px" />

      <template v-else-if="filteredLogs.length">
        <div class="bare-table">
          <DataTable
            ref="dt"
            :value="filteredLogs"
            dataKey="log_id"
            :sortField="sortColumn ? null : 'timestamp'"
            :sortOrder="-1"
            :rowHover="true"
            class="bare-table-inner"
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

            <Column field="timestamp"    header="Last Update"         :sortable="false" style="min-width: 14rem">
              <template #body="{ data }">{{ formatDate(data.timestamp, true) }}</template>
            </Column>
            <Column field="user_email"   header="User ID"             :sortable="false" style="min-width: 12rem" />
            <Column field="role"         header="Role"                :sortable="false" style="min-width: 7rem" />
            <Column field="action"       header="Action"              :sortable="false" style="min-width: 8rem" />
            <Column field="log_id"       header="Identifier"          :sortable="false" style="min-width: 13rem" />
            <Column field="module"       header="Module"              :sortable="false" style="min-width: 7rem" />
            <Column field="submodule"    header="Submodule"           :sortable="false" style="min-width: 8rem" />
            <Column field="status"       header="Status"              :sortable="false" style="min-width: 7rem">
              <template #body="{ data }">
                <Tag :value="data.status" :severity="getStatusLabel(data.status)" />
              </template>
            </Column>
            <Column field="ip_address"   header="IP Address"          :sortable="false" style="min-width: 8rem" />
            <Column field="ip_address2"  header="IP Address 2"        :sortable="false" style="min-width: 8rem" />
            <Column field="ip_address3"  header="IP Address 3"        :sortable="false" style="min-width: 8rem" />
            <Column field="description"  header="Description"         :sortable="false" style="min-width: 18rem" />
            <Column field="device_info"  header="Device Info"         :sortable="false" style="min-width: 16rem" />
            <Column field="session_id"   header="Session ID"          :sortable="false" style="min-width: 16rem" />
            <Column field="login_time"   header="Last Login"          :sortable="false" style="min-width: 14rem">
              <template #body="{ data }">{{ formatDate(data.login_time, true) }}</template>
            </Column>
            <Column field="logout_time"  header="Last Logout"         :sortable="false" style="min-width: 14rem">
              <template #body="{ data }">{{ formatDate(data.logout_time, true) }}</template>
            </Column>
            <Column field="login_type"          header="Login Type"          :sortable="false" style="min-width: 8rem" />
            <Column field="api_endpoints"       header="API Endpoint"        :sortable="false" style="min-width: 18rem" />
            <Column field="database_involved"   header="Database Involved"   :sortable="false" style="min-width: 11rem" />
            <Column field="application_version" header="App Version"         :sortable="false" style="min-width: 8rem" />
            <Column field="error_codes"         header="Error Code"          :sortable="false" style="min-width: 8rem" />
            <Column field="job_id"              header="Job ID"              :sortable="false" style="min-width: 8rem" />
            <Column field="job_judged_by"       header="Approver/Rejector"   :sortable="false" style="min-width: 10rem" />
          </DataTable>
        </div>

        <div class="flex justify-content-between align-items-center mt-4 pt-3" style="border-top: 1px solid var(--surface-border)">
          <span class="text-xs text-color-secondary">
            Showing {{ currentPage * pageSize + 1 }}–{{ currentPage * pageSize + filteredLogs.length }} of {{ totalSize }}
          </span>
          <div class="flex align-items-center gap-2">
            <span class="text-xs text-color-secondary">Rows per page</span>
            <Dropdown v-model="selectedPerPage" :options="[20, 50, 80, 100]" class="w-7rem" />
            <Paginator
              :totalRecords="totalSize"
              :perPage="pageSize"
              :currentPage="currentPage"
              @update:currentPage="onPage"
            />
          </div>
        </div>
      </template>

      <div v-else-if="!loadingTable" class="flex flex-column align-items-center justify-content-center gap-2 py-6 text-color-secondary">
        <i class="pi pi-list text-3xl opacity-40" />
        <span class="text-sm">No logs found. Adjust filters and apply.</span>
      </div>
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
  'IP Address2': 'ip_address2',
  'IP Address3': 'ip_address3',
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

// search
const searchColumns = ref(Object.keys(COLUMN_MAP))
const selectedSortColumn = ref(null)
const selectedSortOrder = ref(true)
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
  sortColumn.value = COLUMN_MAP[selectedSortColumn.value]
  sortOrder.value = selectedSortOrder.value ? 'asc' : 'desc'

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

const download = () => {
  const data = preprocessDownloadData(
    JSON.parse(JSON.stringify(dt.value.processedData))
  )
  saveFile(data, 'xlsx', 'auditlog')
}

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
      if (obj.hasOwnProperty(field)) {
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

.sort-dir-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  flex-shrink: 0;
  border: 1px solid var(--surface-border-input);
  border-radius: 2px;
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s;
}
.sort-dir-btn:hover {
  border-color: var(--ink);
  color: var(--text-color);
}

.bare-table { margin: 0 -1.25rem; }
:deep(.bare-table-inner .p-datatable-thead > tr > th) {
  background: transparent;
  color: var(--text-color-muted);
  font-weight: 700;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border: 0;
  border-bottom: 2px solid var(--ink);
  padding: 0.6rem 1.25rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border-row);
  padding: 0.75rem 1.25rem;
  font-size: 0.875rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr:hover > td) { background: var(--surface-hover); }
:deep(.bare-table-inner .p-datatable-tbody > tr:last-child > td) { border-bottom: 0; }
:deep(.bare-table-inner .p-datatable-header) {
  background: transparent;
  border: 0;
  padding: 0 1.25rem 0.75rem;
}
</style>
