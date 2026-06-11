<script setup>
import { ref, onMounted, computed, watch, watchEffect } from 'vue'
import { useStore } from 'vuex'
import { useToast } from 'primevue/usetoast'
import { formatCurrency, formatNumber } from '@/components/Table/utils'
import { getJobDetails } from '@/utils'
import { saveFile } from '@/views/composables/views.js'
import { API_URL } from '@/api/httpClient'
import Paginator from '../Paginator.vue'

// Define props
const props = defineProps({
  module: {
    type: String,
    required: true
  },
  submodule: {
    type: String,
    required: true
  },
  type: {
    type: String,
    default: 'input'
  },
  dbName: {
    type: String,
    default: 'input'
  },
  loadingStaging: {
    type: Boolean,
    default: false
  },
  jobId: {
    type: String,
    default: null
  },
  columns: {
    type: Array,
    default: () => []
  },
  filterColumns: {
    type: String,
    default: null
  },
  filterValues: {
    type: String,
    default: null
  },
  streamDownload: {
    type: Boolean,
    default: true
  },
  currencyColumns: {
    type: Array,
    default: () => []
  },
  nonFormattedNumericColumns: {
    type: Array,
    default: () => [
      // Common
      'CIF',
      'YEAR',
      'BaseYear',
      'Year',
      'base_year',
      'end_year',
      // FRTB
      'against IDR',
      'against USD',
      'Par Rate',
      'Zero Cpn. ACT/365',
      'Discount Factor',
      'Forward 3M',
      // PCAF
      'Transaction ID (Norek)'
    ]
  },
  showSuccessToast: {
    type: Boolean,
    default: true
  }
})

// services
const store = useStore()
const toast = useToast()

// props reactive
const module = computed(() => props.module)
const submodule = computed(() => props.submodule)
const type = computed(() => props.type)
const dbName = computed(() => props.dbName)
const loadingStaging = computed(() => props.loadingStaging)
const filterColumns = computed(() => props.filterColumns)
const filterValues = computed(() => props.filterValues)

// refs
const jobData = ref([])
const currentPage = ref(0)
const totalSize = ref(0)
const pageSize = ref(20)
const selectedPerPage = ref(20)
const loadingTable = ref(true)
const emitLoadStaging = ref(true)
const emitSize = ref(null)
const useStaging = ref(false)
const stagingJobId = ref(null)

const searchColumns = ref([])
const selectedFilterColumn = ref(null)
const selectedFilterValue = ref(null)
const selectedSortColumn = ref(null)
const selectedSortOrder = ref(true)
const additionalFilterColumn = ref(null)
const additionalFilterValue = ref(null)
const sortColumn = ref(null)
const sortOrder = ref('asc')

const resetInnerFilters = () => {
  selectedFilterColumn.value = null
  selectedFilterValue.value = null
  selectedSortColumn.value = null
  selectedSortOrder.value = true
  additionalFilterColumn.value = null
  additionalFilterValue.value = null
  sortColumn.value = null
  sortOrder.value = 'asc'
}

// emits
const emit = defineEmits(['update:loadingStaging', 'emitSize', 'loadComplete'])
watch(emitLoadStaging, (newVal) => {
  emit('update:loadingStaging', newVal)
})
watch(emitSize, (newVal) => {
  emit('emitSize', newVal)
})

onMounted(async () => {
  if (!loadingStaging.value) {
    loadJob(
      module.value,
      submodule.value,
      type.value,
      dbName.value,
      filterColumns.value,
      filterValues.value
    )
  }
})

watch(
  [module, submodule, dbName, type, filterColumns, filterValues],
  async ([m, s, db, t, fcols, fvals]) => {
    resetInnerFilters()
    loadJob(m, s, t, db, fcols, fvals)
  }
)

const onConfirmSelect = () => {
  currentPage.value = 0
  loadingTable.value = true

  additionalFilterColumn.value = selectedFilterColumn.value || ''
  additionalFilterValue.value = selectedFilterValue.value || ''
  sortColumn.value = selectedSortColumn.value || ''
  sortOrder.value = selectedSortOrder.value ? 'desc' : 'asc'

  if (useStaging.value) {
    // emitLoadStaging.value = true // this will trigger watchEffect to load staging data
    loadStaging(
      module.value,
      submodule.value,
      dbName.value,
      filterColumns.value + '\x1e' + additionalFilterColumn.value,
      filterValues.value + '\x1f' + additionalFilterValue.value,
      sortColumn.value,
      sortOrder.value
    )
  } else {
    loadJob(
      module.value,
      submodule.value,
      type.value,
      dbName.value,
      filterColumns.value + '\x1e' + additionalFilterColumn.value,
      filterValues.value + '\x1f' + additionalFilterValue.value,
      sortColumn.value,
      sortOrder.value
    )
  }
}

const loadJob = async (m, s, t, db, fcols, fvals, sortCol, sortOrder) => {
  currentPage.value = 0
  loadingTable.value = true

  try {
    await getJobDetails({
      store: store,
      module: m,
      submodule: s,
      type: t,
      dbName: db,
      page: currentPage.value,
      page_size: pageSize.value,
      jobId: props.jobId,
      columns: props.columns.join('\x1e'),
      filter_columns: fcols,
      filter_values: fvals,
      sort_column: sortCol,
      sort_order: sortOrder,
      get_size: true
    }).then((res) => {
      if (res) {
        jobData.value = res.data
        totalSize.value = res.total_size
        searchColumns.value =
          jobData.value.length > 0 ? Object.keys(jobData.value[0]) : searchColumns.value
      } else {
        jobData.value = []
      }
    })
  } catch (err) {
    const msg = err.response?.data?.message || err.message
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load ' + db + '. ' + msg,
      life: 5000
    })
  } finally {
    loadingTable.value = false
    emitLoadStaging.value = false
  }
}

const loadStaging = async (m, s, db, fcols, fvals, sortCol, sortOrder) => {
  loadingTable.value = true
  useStaging.value = true
  let size = 0

  try {
    await store
      .dispatch('getStagingInput', {
        module: m,
        submodule: s,
        dbName: db,
        page: 0,
        page_size: pageSize.value,
        filter_columns: fcols,
        filter_values: fvals,
        sort_column: sortCol,
        sort_order: sortOrder,
        get_size: true
      })
      .then((res) => {
        if (res?.data) {
          const data = res.data[db]
          jobData.value = JSON.parse(data['data'])
          stagingJobId.value = data['job_id']
          searchColumns.value =
            jobData.value.length > 0 ? Object.keys(jobData.value[0]) : searchColumns.value
          totalSize.value = data['total_size']
          emitSize.value = size
          currentPage.value = 0

          if (props.showSuccessToast) {
            toast.add({
              severity: 'success',
              summary: 'Success',
              detail: db + ' loaded successfully',
              life: 3000
            })
          }

          // Emit load complete event for tracking
          emit('loadComplete', { dbName: db, success: true })
        }
      })
  } catch (err) {
    const msg = err.response?.data?.message || err.message
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load ' + db + '. ' + msg,
      life: 5000
    })
    // Emit load complete event even on error
    emit('loadComplete', { dbName: db, success: false, error: msg })
  } finally {
    loadingTable.value = false
  }
}

watchEffect(async () => {
  if (loadingStaging.value) {
    try {
      emitLoadStaging.value = true

      // reset inner filters
      resetInnerFilters()

      await loadStaging(
        module.value,
        submodule.value,
        dbName.value,
        filterColumns.value,
        filterValues.value
      )
    } finally {
      emitLoadStaging.value = false
    }
  }
})

// Pagination
const onPage = (page) => {
  currentPage.value = page
}

watch(selectedPerPage, async (p) => {
  pageSize.value = p
  currentPage.value = 0
})

watch([currentPage, pageSize], ([p, p_size]) => {
  loadingTable.value = true

  if (useStaging.value) {
    store
      .dispatch('getStagingInput', {
        module: module.value,
        submodule: submodule.value,
        dbName: dbName.value,
        page: p,
        page_size: p_size,
        jobId: stagingJobId.value,
        filter_columns: filterColumns.value + '\x1e' + additionalFilterColumn.value,
        filter_values: filterValues.value + '\x1f' + additionalFilterValue.value,
        sort_column: sortColumn.value,
        sort_order: sortOrder.value
      })
      .then((res) => {
        if (res?.data) {
          const data = res.data[dbName.value]
          jobData.value = JSON.parse(data['data'])
        }
      })
      .catch((err) => {
        const msg = err.response?.data?.message || err.message
        toast.add({
          severity: 'error',
          summary: 'Error',
          detail: 'Failed to load ' + dbName.value + '. ' + msg,
          life: 5000
        })
      })
      .finally(() => {
        loadingTable.value = false
      })
  } else {
    getJobDetails({
      store: store,
      module: module.value,
      submodule: submodule.value,
      type: type.value,
      dbName: dbName.value,
      page: p,
      page_size: p_size,
      jobId: props.jobId,
      columns: props.columns.join('\x1e'),
      filter_columns: filterColumns.value + '\x1e' + additionalFilterColumn.value,
      filter_values: filterValues.value + '\x1f' + additionalFilterValue.value,
      sort_column: sortColumn.value,
      sort_order: sortOrder.value
    })
      .then((data) => {
        if (data) {
          jobData.value = data
        } else {
          jobData.value = []
        }
      })
      .catch((err) => {
        const msg = err.response?.data?.message || err.message
        toast.add({
          severity: 'error',
          summary: 'Error',
          detail: 'Failed to load ' + dbName.value + '. ' + msg,
          life: 5000
        })
      })
      .finally(() => {
        loadingTable.value = false
      })
  }
})

//-------Table Settings-------//
const jobColumns = computed(() => {
  if (!jobData.value || jobData.value.length === 0) {
    return []
  }
  const ret = Object.keys(jobData.value[0]).map((key) => {
    return {
      field: key,
      header: key,
      sortable: false
    }
  })

  return ret
})

//-------Download-------//
const download = async () => {
  loadAndSave(module.value + '_' + submodule.value + '_' + dbName.value, 'xlsx')
}

const downloadOptions = [
  {
    label: 'csv',
    icon: 'fi fi-rr-file-csv',
    command: () => {
      loadAndSave(module.value + '_' + submodule.value + '_' + dbName.value, 'csv')
    }
  },
  {
    label: 'xlsx',
    icon: 'fi fi-rr-file-excel',
    command: () => {
      loadAndSave(module.value + '_' + submodule.value + '_' + dbName.value, 'xlsx')
    }
  }
]

const loadingDownload = ref(false)
const downloadProgress = ref({})
// Helper to check if a value is numeric
const isNumericValue = (value) => {
  if (value === null || value === undefined || value === '') return false
  return !Number.isNaN(Number.parseFloat(value)) && Number.isFinite(value)
}

const loadAndSave = async (fileName, ext) => {
  const uniqueID = crypto.randomUUID()
  const toastId = 'download-progress-toast-' + fileName + '-' + uniqueID

  try {
    downloadProgress.value[toastId] = 0

    // toast.add({
    //   severity: 'info',
    //   summary: `Downloading ${dbName.value}.${ext}`,
    //   group: 'download',
    //   life: 0, // Set to 0 to prevent auto-close
    //   sticky: true, // Make it sticky so it doesn't disappear
    //   id: toastId
    // })

    if (useStaging.value) {
      // loadingDownload.value = true
      await store
        .dispatch('downloadFile', {
          jobId: stagingJobId.value,
          module: props.module,
          submodule: props.submodule,
          type: type.value,
          dbName: dbName.value,
          fileType: ext,
          downloadFileName: fileName,
          isStaging: true
        })
        .then(async (res) => {
          if (res?.data?.download_url && res?.data?.download_token) {
            // Show notification for split files
            if (res.data.is_zip) {
              toast.add({
                severity: 'info',
                summary: 'Large Dataset',
                detail: 'File has been split into multiple parts and packaged as ZIP',
                life: 5000
              })
            }

            // Use hidden form POST to avoid token in URL query parameters
            const form = document.createElement('form')
            form.method = 'POST'
            form.action = `${API_URL}${res.data.download_url}`
            form.style.display = 'none'

            const tokenInput = document.createElement('input')
            tokenInput.type = 'hidden'
            tokenInput.name = 'token'
            tokenInput.value = res.data.download_token
            form.appendChild(tokenInput)

            document.body.appendChild(form)
            form.submit()
            document.body.removeChild(form)

            toast.add({
              severity: 'success',
              summary: 'Download Started',
              detail: `${res.data.filename} download has started.`,
              life: 3000
            })
          }
        })
        .catch((err) => {
          const msg = err.response?.data?.message || err.message
          toast.add({
            severity: 'error',
            summary: 'Error',
            detail: 'Fail to prepare download. ' + msg,
            life: 3000
          })
        })
    } else {
      let id = props.jobId
      if (!id) {
        const jobRes = await store.dispatch('getLatestJob', {
          module: props.module,
          submodule: props.submodule
        })
        const currentJob = jobRes?.data
        if (!currentJob) {
          return null
        }
        id = currentJob.job_id
      }

      // Request download URL instead of streaming file
      await store
        .dispatch('downloadFile', {
          jobId: id,
          module: props.module,
          submodule: props.submodule,
          type: type.value,
          dbName: dbName.value,
          fileType: ext,
          downloadFileName: fileName
        })
        .then(async (res) => {
          if (res?.data?.download_url && res?.data?.download_token) {
            // Show notification for split files
            if (res.data.is_zip) {
              toast.add({
                severity: 'info',
                summary: 'Large Dataset',
                detail: 'File has been split into multiple parts and packaged as ZIP',
                life: 5000
              })
            }

            // Use hidden form POST to avoid token in URL query parameters
            const form = document.createElement('form')
            form.method = 'POST'
            form.action = `${API_URL}${res.data.download_url}`
            form.style.display = 'none'

            const tokenInput = document.createElement('input')
            tokenInput.type = 'hidden'
            tokenInput.name = 'token'
            tokenInput.value = res.data.download_token
            form.appendChild(tokenInput)

            document.body.appendChild(form)
            form.submit()
            document.body.removeChild(form)

            toast.add({
              severity: 'success',
              summary: 'Download Started',
              detail: `${res.data.filename} download has started.`,
              life: 3000
            })
          }
        })
        .catch((err) => {
          const msg = err.response?.data?.message || err.message
          toast.add({
            severity: 'error',
            summary: 'Error',
            detail: 'Fail to prepare download. ' + msg,
            life: 3000
          })
        })
    }
  } catch (err) {
    const msg = err.response?.data?.message || err.message
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Fail to download file. ' + msg,
      life: 3000
    })
  } finally {
    toast.remove({ id: toastId })
    delete downloadProgress.value[toastId]
    loadingDownload.value = false
  }
}
</script>

<template>
  <div>
    <Toast position="bottom-right" group="download">
      <template #container="{ message }">
        <section class="flex p-3 gap-3 w-full bg-black-alpha-90" style="border-radius: 10px">
          <i class="pi pi-cloud-download text-primary-500 text-2xl"></i>
          <div class="flex flex-column gap-3 w-full">
            <p class="m-0 font-semibold text-base text-white">{{ message.summary }}</p>
            <p class="m-0 text-base text-700">{{ message.detail }}</p>
            <div class="flex flex-column gap-2">
              <ProgressBar
                :value="downloadProgress[message.id] ? downloadProgress[message.id] : 0"
                :showValue="false"
                :style="{ height: '4px' }"
              ></ProgressBar>
              <span class="text-right text-xs text-white"
                >{{ downloadProgress[message.id] ? downloadProgress[message.id] : 0 }}%
                downloaded...</span
              >
            </div>
          </div>
        </section>
      </template>
    </Toast>
    <Panel toggleable collapsed>
      <template #header>
        <span class="text-lg font-semibold">Search Criteria</span>
      </template>

      <div class="flex justify-content-between gap-5 mt-4">
        <div class="w-6 flex gap-2">
          <Dropdown
            v-model="selectedFilterColumn"
            :options="searchColumns"
            :loading="loadingTable && searchColumns.length === 0"
            :filter="true"
            :placeholder="'Filter By'"
            showClear
            class="w-5"
          />
          <InputText type="text" v-model="selectedFilterValue" class="w-6" :placeholder="'Value'" />
        </div>

        <div class="w-6 flex justify-content-end gap-2">
          <Dropdown
            v-model="selectedSortColumn"
            :options="searchColumns"
            :loading="loadingTable && searchColumns.length === 0"
            :filter="true"
            :placeholder="'Sort By'"
            showClear
            class="w-3"
          />
          <ToggleButton
            v-model="selectedSortOrder"
            :onLabel="''"
            :offLabel="''"
            onIcon="pi pi-sort-amount-up"
            offIcon="pi pi-sort-amount-down"
            class="w-1"
          />
        </div>
      </div>
      <div class="flex justify-content-begin mt-5">
        <Button label="Apply filters" aria-label="confirm" @click="onConfirmSelect" />
      </div>
    </Panel>

    <div class="card mt-4">
      <Skeleton v-if="loadingTable" width="100%" height="150px"></Skeleton>
      <div v-else>
        <div v-if="jobData">
          <DataTable
            v-if="jobData"
            :value="jobData"
            :loading="loadingTable"
            sortMode="multiple"
            removableSort
            :rowHover="true"
            resizableColumns
            columnResizeMode="fit"
            :pt="{
              column: {
                bodycell: ({ state }) => ({
                  class: [{ 'pt-0 pb-0': state['d_editing'] }]
                })
              }
            }"
            tableStyle="min-width: 50rem"
          >
            <template #empty> No data found. </template>
            <template #loading> Loading data. Please wait. </template>

            <Column
              v-for="col of jobColumns"
              :key="col.field"
              :field="col.field"
              :header="col.header"
              :sortable="col.sortable"
              :filterField="col.field"
              style="min-width: 10rem"
            >
              <template #body="{ data, field }">
                <span style="white-space: pre-wrap">
                  {{
                    isNumericValue(data[field]) && !nonFormattedNumericColumns.includes(field)
                      ? formatNumber(data[field], 2)
                      : data[field]
                  }}
                </span>
              </template>
              <template #filter="{ filterModel, filterCallback }">
                <InputText
                  v-model="filterModel.value"
                  type="text"
                  @input="filterCallback()"
                  class="p-column-filter"
                  placeholder="Search"
                />
              </template>
            </Column>
          </DataTable>
          <div v-if="totalSize" class="flex justify-content-between align-items-center mt-4">
            <div>
              <!-- <DownloadButton :data="jobData" :filename="module + '_' + submodule + '_' + dbName" /> -->
              <SplitButton
                :label="'Save'"
                menuButtonIcon="pi pi-download"
                outlined
                :model="downloadOptions"
                @click="download"
              />
            </div>
            <h6 class="text-500">
              Showing {{ currentPage * pageSize + 1 }} to
              {{ currentPage * pageSize + jobData.length }} out of {{ totalSize }}
            </h6>

            <div class="flex gap-2">
              <Dropdown v-model="selectedPerPage" :options="[20, 50, 100]" />
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
    </div>
  </div>
</template>
