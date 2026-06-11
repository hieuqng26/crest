<template>
  <div>
    <Card>
      <template #title>Search Criteria</template>
      <template #content>
        <div class="flex justify-content-center gap-5 mt-2">
          <div class="w-full">
            <label for="dateFromSelect" class="font-bold block mb-2"
              >Date From</label
            >
            <Calendar
              inputID="dateFromSelect"
              v-model="dateFrom"
              showIcon
              iconDisplay="input"
              class="w-full"
            />
          </div>

          <div class="w-full">
            <label for="dateToSelect" class="font-bold block mb-2"
              >Date To</label
            >
            <Calendar
              inputID="dateToSelect"
              v-model="dateTo"
              showIcon
              iconDisplay="input"
              class="w-full"
            />
          </div>

          <div class="w-full">
            <label for="userEmailInput" class="font-bold block mb-2"
              >User ID</label
            >
            <InputText
              type="text"
              inputID="userEmailInput"
              v-model="userEmailInput"
              class="w-full"
            />
          </div>
        </div>
        <div class="flex justify-content-center gap-5 mt-5">
          <div class="w-full">
            <label for="moduleSelect" class="font-bold block mb-2"
              >Module</label
            >
            <MultiSelect
              inputID="moduleSelect"
              v-model="selectedModules"
              :loading="loadingDD"
              :options="moduleOptions"
              :filter="moduleOptions.length >= 5"
              placeholder="Please Select"
              :maxSelectedLabels="3"
              class="w-full"
            />
          </div>

          <div class="w-full">
            <label for="submoduleSelect" class="font-bold block mb-2"
              >Sub-Module</label
            >
            <MultiSelect
              inputID="submoduleSelect"
              v-model="selectedSubmodules"
              :loading="loadingDD"
              :options="submoduleOptions"
              :filter="submoduleOptions.length >= 5"
              placeholder="Please Select"
              :maxSelectedLabels="3"
              class="w-full"
            />
          </div>

          <div class="w-full">
            <label for="actionSelect" class="font-bold block mb-2"
              >Action</label
            >
            <MultiSelect
              inputID="actionSelect"
              v-model="selectedActions"
              :loading="loadingDD"
              :options="actionOptions"
              :filter="actionOptions.length >= 5"
              placeholder="Please Select"
              :maxSelectedLabels="3"
              class="w-full"
            />
          </div>
        </div>
        <div class="w-6 flex justify-content-start mt-5">
          <div class="w-full">
            <label for="sortDD" class="font-bold block mb-2">Sort By</label>
            <div inputID="sortDD">
              <Dropdown
                v-model="selectedSortColumn"
                :options="searchColumns"
                :loading="loadingTable && searchColumns.length === 0"
                :filter="true"
                showClear
                class="w-3"
              />
              <ToggleButton
                v-model="selectedSortOrder"
                :onLabel="''"
                :offLabel="''"
                onIcon="pi pi-sort-amount-up"
                offIcon="pi pi-sort-amount-down"
                class="w-1 ml-2"
              />
            </div>
          </div>
        </div>
        <div class="flex justify-content-begin mt-5">
          <Button
            label="Apply filters"
            aria-label="confirm"
            @click="onConfirmSelect"
          />
        </div>
      </template>
    </Card>
    <div class="card mt-4">
      <Skeleton v-if="loadingTable" width="100%" height="150px"></Skeleton>
      <DataTable
        v-else
        v-if="filteredLogs.length"
        ref="dt"
        :value="filteredLogs"
        dataKey="log_id"
        :sortField="sortColumn ? null : 'timestamp'"
        :sortOrder="-1"
        removableSort
        :rowHover="true"
      >
        <!-- Header -->
        <template #header>
          <div
            class="flex flex-wrap gap-2 align-items-center justify-content-between"
          >
            <h5 class="m-0 p-0 text-color-secondary">
              Search Result (showing {{ currentPage * pageSize + 1 }} to
              {{ currentPage * pageSize + filteredLogs.length }} out of
              {{ totalSize }} entries)
            </h5>
          </div>
        </template>

        <!-- Main Columns -->
        <!-- Main Columns -->
        <Column
          field="timestamp"
          header="Last Update"
          :sortable="false"
          style="min-width: 18rem"
        >
          <template #body="slotProps">
            {{ formatDate(slotProps.data.timestamp, true) }}
          </template>
        </Column>
        <Column
          field="user_email"
          header="User ID"
          :sortable="false"
          style="min-width: 12rem"
        ></Column>
        <Column
          field="role"
          header="Role"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="action"
          header="Action"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="log_id"
          header="Identifier"
          :sortable="false"
          style="min-width: 14rem"
        ></Column>
        <Column
          field="module"
          header="Module"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="submodule"
          header="Submodule"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="status"
          header="Status"
          :sortable="false"
          style="min-width: 8rem"
        >
          <template #body="slotProps">
            <Tag
              :value="slotProps.data.status"
              :severity="getStatusLabel(slotProps.data.status)"
            />
          </template>
        </Column>
        <Column
          field="ip_address"
          header="IP Address"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="ip_address2"
          header="IP Address2"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="ip_address3"
          header="IP Address3"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="description"
          header="Description"
          :sortable="false"
          style="min-width: 20rem"
        ></Column>
        <Column
          field="device_info"
          header="Device Info"
          :sortable="false"
          style="min-width: 20rem"
        ></Column>
        <Column
          field="session_id"
          header="Session ID"
          :sortable="false"
          style="min-width: 20rem"
        ></Column>
        <Column
          field="login_time"
          header="Last Login"
          :sortable="false"
          style="min-width: 18rem"
        >
          <template #body="slotProps">
            {{ formatDate(slotProps.data.login_time, true) }}
          </template>
        </Column>
        <Column
          field="logout_time"
          header="Last Logout"
          :sortable="false"
          style="min-width: 18rem"
        >
          <template #body="slotProps">
            {{ formatDate(slotProps.data.logout_time, true) }}
          </template>
        </Column>
        <Column
          field="login_type"
          header="Login Type"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="api_endpoints"
          header="API Endpoint"
          :sortable="false"
          style="min-width: 20rem"
        ></Column>
        <Column
          field="database_involved"
          header="Database Involved"
          :sortable="false"
          style="min-width: 12rem"
        ></Column>
        <Column
          field="application_version"
          header="Application Version"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="error_codes"
          header="Error Code"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="job_id"
          header="Job ID"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
        <Column
          field="job_judged_by"
          header="Approver/Rejector"
          :sortable="false"
          style="min-width: 8rem"
        ></Column>
      </DataTable>

      <div
        v-if="totalSize"
        class="flex justify-content-between align-items-center mt-4"
      >
        <div>
          <SplitButton
            label="Save"
            icon="pi pi-check"
            menuButtonIcon="pi pi-download"
            outlined
            :model="downloadOptions"
            @click="download"
          />
        </div>
        <h6 class="text-500">
          Showing {{ currentPage * pageSize + 1 }} to
          {{ currentPage * pageSize + filteredLogs.length }} out of
          {{ totalSize }}
        </h6>

        <div class="flex gap-2">
          <Dropdown v-model="selectedPerPage" :options="[20, 50, 80, 100]" />
          <div>
            <Paginator
              :totalRecords="totalSize"
              :perPage="pageSize"
              :currentPage="currentPage"
              @update:currentPage="onPage"
            />
          </div>
        </div>
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
