<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import datasetsAPI from '@/api/datasetsAPI'
import { datasets, loading, fetchDatasets, addDataset, deleteDataset } from './datasetsStore'
import { fmtDate as formatDate } from '@/utils/datetime'

const router = useRouter()
const toast = useToast()

const search = ref('')
const sourceFilter = ref(null)
const sourceOptions = [
  { label: 'All',        value: null },
  { label: 'Upload',     value: 'upload' },
  { label: 'Live Query', value: 'live_query' }
]

const sourceSeverity = (s) => (s === 'upload' ? 'info' : 'warning')
const statusSeverity = (s) => ({ ready: 'success', processing: 'warning', error: 'danger' }[s] ?? 'secondary')

const filtered = computed(() =>
  datasets.value.filter(d =>
    (!sourceFilter.value || d.source === sourceFilter.value) &&
    d.name.toLowerCase().includes(search.value.toLowerCase())
  )
)

const view = (d) => router.push({ name: 'dataset_view', params: { id: d.id } })

const onDelete = async (d) => {
  await deleteDataset(d.id)
  toast.add({ severity: 'success', summary: 'Deleted', detail: d.name, life: 2000 })
}

// --- Bulk delete ---
const selectMode = ref(false)
const selection = ref([])
const confirmingBulkDelete = ref(false)

const exitSelectMode = () => {
  selectMode.value = false
  selection.value = []
  confirmingBulkDelete.value = false
}

const bulkDelete = async () => {
  const ids = selection.value.map(d => d.id)
  try {
    const { data } = await datasetsAPI.bulkDelete(ids)
    const deletedSet = new Set(ids)
    datasets.value = datasets.value.filter(d => !deletedSet.has(d.id))
    toast.add({ severity: 'success', summary: 'Deleted', detail: `${data.deleted} dataset${data.deleted !== 1 ? 's' : ''} deleted`, life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
  exitSelectMode()
}

onMounted(fetchDatasets)

// --- Upload dialog ---
const uploadVisible = ref(false)
const uploading = ref(false)
const uploadFile = ref(null)
const uploadName = ref('')
const uploadKind = ref('calibration')

const KIND_OPTIONS = [
  { label: 'Calibration',  value: 'calibration' },
  { label: 'Credit',       value: 'credit' },
  { label: 'Forecast',     value: 'forecast' },
]

const openUpload = () => {
  uploadFile.value = null
  uploadName.value = ''
  uploadKind.value = 'calibration'
  uploading.value = false
  uploadVisible.value = true
}

const onSelectFile = (event) => {
  uploadFile.value = event.files[0]
  if (!uploadName.value) uploadName.value = event.files[0].name.replace(/\.[^.]+$/, '')
}

const saveUpload = async () => {
  if (!uploadFile.value) { toast.add({ severity: 'warn', summary: 'Select a file first', life: 2500 }); return }
  if (!uploadName.value.trim()) { toast.add({ severity: 'warn', summary: 'Dataset name is required', life: 2500 }); return }
  uploading.value = true
  try {
    const { data } = await datasetsAPI.upload(uploadFile.value, uploadName.value.trim(), '', uploadKind.value)
    addDataset(data)
    toast.add({ severity: 'success', summary: 'Uploaded', detail: data.name, life: 2500 })
    uploadVisible.value = false
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Upload failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    uploading.value = false
  }
}

// --- Live query dialog ---
const queryVisible = ref(false)
const sql = ref('SELECT TOP 100 obligor_id, default_flag, pd_estimate, lgd, ead\nFROM risk_db.dbo.pd_master\nWHERE year >= 2020')
const queryName = ref('')
const running = ref(false)
const preview = ref(null)

const openQuery = () => { preview.value = null; running.value = false; queryName.value = ''; queryVisible.value = true }

const runQuery = async () => {
  running.value = true
  preview.value = null
  try {
    const { data } = await datasetsAPI.query(sql.value, queryName.value || 'preview', '')
    preview.value = {
      columns: data.schema_json ? JSON.parse(data.schema_json).columns ?? [] : [],
      total_rows: data.row_count ?? 0,
      dataset: data
    }
    if (!queryName.value) queryName.value = data.name
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Query failed', detail: e?.response?.data?.error ?? e.message, life: 5000 })
  } finally {
    running.value = false
  }
}

const saveQuery = () => {
  if (!preview.value?.dataset) {
    toast.add({ severity: 'warn', summary: 'Run the query first', life: 2500 }); return
  }
  addDataset(preview.value.dataset)
  toast.add({ severity: 'success', summary: 'Registered', detail: preview.value.dataset.name, life: 2500 })
  queryVisible.value = false
}
</script>

<template>
  <div class="p-4">
    <div class="flex align-items-center justify-content-between mb-4">
      <div>
        <h2 class="text-2xl font-semibold m-0">Datasets</h2>
        <p class="text-color-secondary text-sm m-0 mt-1">Registered datasets available for calibration.</p>
      </div>
      <div class="flex gap-2">
        <Button label="Upload"     icon="pi pi-upload"   size="small" @click="openUpload" />
        <Button label="Live Query" icon="pi pi-database" size="small" severity="secondary" @click="openQuery" />
      </div>
    </div>

    <div class="surface-card border-round shadow-1 p-4">
      <!-- Toolbar -->
      <div class="flex flex-wrap align-items-center gap-3 mb-3">
        <IconField class="flex-1" style="min-width: 16rem">
          <InputIcon class="pi pi-search" />
          <InputText v-model="search" placeholder="Search datasets…" class="w-full" />
        </IconField>

        <Dropdown
          v-model="sourceFilter"
          :options="sourceOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="All"
          class="w-11rem"
        />

        <template v-if="!selectMode">
          <Button label="Select" icon="pi pi-check-square" size="small" severity="secondary" text @click="selectMode = true" />
        </template>
        <template v-else>
          <span class="text-sm text-color-secondary">{{ selection.length }} selected</span>
          <template v-if="!confirmingBulkDelete">
            <Button
              label="Delete selected"
              icon="pi pi-trash"
              size="small"
              severity="danger"
              :disabled="selection.length === 0"
              @click="confirmingBulkDelete = true"
            />
          </template>
          <template v-else>
            <span class="text-sm font-medium text-red-400">Delete {{ selection.length }} dataset{{ selection.length !== 1 ? 's' : '' }}?</span>
            <Button label="Confirm" icon="pi pi-check" size="small" severity="danger" @click="bulkDelete" />
            <Button label="Cancel"  size="small" severity="secondary" text @click="confirmingBulkDelete = false" />
          </template>
          <Button icon="pi pi-times" size="small" severity="secondary" text rounded @click="exitSelectMode" v-tooltip.top="'Exit select mode'" />
        </template>
      </div>

      <DataTable
        :value="filtered"
        v-model:selection="selection"
        :selectionMode="selectMode ? 'multiple' : null"
        dataKey="id"
        size="small"
        :paginator="filtered.length > 15"
        :rows="15"
      >
        <template #empty>
          <div class="text-center p-4 text-color-secondary">
            <i class="pi pi-inbox text-3xl block mb-2" />
            <p class="m-0">No datasets match your filters.</p>
          </div>
        </template>

        <Column v-if="selectMode" selectionMode="multiple" style="width: 3rem" />

        <Column field="id" header="ID" style="width:4rem" sortable />
        <Column field="name" header="Name" sortable />
        <Column field="source" header="Source" sortable>
          <template #body="{ data }">
            <Tag :value="data.source === 'live_query' ? 'Live Query' : 'Upload'" :severity="sourceSeverity(data.source)" />
          </template>
        </Column>
        <Column field="kind" header="Type" sortable>
          <template #body="{ data }">
            <Tag
              :value="{ calibration: 'Calibration', credit: 'Credit', forecast: 'Forecast' }[data.kind] ?? data.kind ?? '—'"
              :severity="{ calibration: 'secondary', credit: 'info', forecast: 'warning' }[data.kind] ?? 'secondary'"
            />
          </template>
        </Column>
        <Column field="row_count" header="Rows" sortable>
          <template #body="{ data }">{{ data.row_count?.toLocaleString() }}</template>
        </Column>
        <Column field="created_by" header="Created By" sortable />
        <Column field="created_at" header="Date" sortable>
          <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
        </Column>
        <Column field="status" header="Status" sortable>
          <template #body="{ data }">
            <Tag :value="data.status" :severity="statusSeverity(data.status)" />
          </template>
        </Column>
        <Column v-if="!selectMode" header="" style="width:7rem">
          <template #body="{ data }">
            <div class="flex gap-1 justify-content-end">
              <Button icon="pi pi-eye"   text rounded size="small" v-tooltip.top="'View'"   @click="view(data)" />
              <Button icon="pi pi-trash" text rounded size="small" severity="danger" v-tooltip.top="'Delete'" @click="onDelete(data)" />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <!-- Upload dialog -->
    <Dialog v-model:visible="uploadVisible" modal :style="{ width: '36rem' }" :draggable="false">
      <template #header>
        <div>
          <div class="text-lg font-semibold">Upload Dataset</div>
          <div class="text-xs text-color-secondary">Supported: CSV, Excel (.xlsx), Parquet</div>
        </div>
      </template>

      <div class="flex flex-column gap-4">
        <FileUpload
          mode="basic"
          name="dataset"
          accept=".csv,.xlsx,.parquet"
          :maxFileSize="104857600"
          :auto="false"
          chooseLabel="Choose file"
          class="w-full"
          @select="onSelectFile"
        />

        <div v-if="uploadFile" class="surface-ground border-round p-3 flex align-items-center gap-2">
          <i class="pi pi-file text-xl text-color-secondary" />
          <span class="text-sm font-mono flex-1 min-w-0 overflow-hidden text-overflow-ellipsis">{{ uploadFile.name }}</span>
          <Tag :value="(uploadFile.size / 1024).toFixed(0) + ' KB'" severity="secondary" />
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Dataset name</label>
          <InputText v-model="uploadName" placeholder="e.g. PD_Corporate_2024" class="w-full" />
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Type</label>
          <Dropdown v-model="uploadKind" :options="KIND_OPTIONS" optionLabel="label" optionValue="value" class="w-full" />
          <div class="text-xs text-color-secondary">
            <span v-if="uploadKind === 'calibration'">Used for model training and backtesting.</span>
            <span v-else-if="uploadKind === 'credit'">Credit portfolio data for KMV / IFRS 9 analysis.</span>
            <span v-else-if="uploadKind === 'forecast'">Feature data for generating forward-looking predictions.</span>
          </div>
        </div>
      </div>

      <ProgressBar v-if="uploading" mode="indeterminate" class="mt-3" style="height:4px" />

      <template #footer>
        <Button label="Cancel" severity="secondary" text @click="uploadVisible = false" />
        <Button label="Upload & Register" icon="pi pi-upload" :loading="uploading" :disabled="!uploadFile || !uploadName.trim()" @click="saveUpload" />
      </template>
    </Dialog>

    <!-- Live query dialog -->
    <Dialog v-model:visible="queryVisible" modal :style="{ width: '56rem' }" :draggable="false">
      <template #header>
        <div>
          <div class="text-lg font-semibold">Live Database Query</div>
          <div class="text-xs text-color-secondary">Query the risk database. Results are registered as a dataset.</div>
        </div>
      </template>

      <div class="flex flex-column gap-3">
        <Textarea v-model="sql" rows="6" class="w-full font-mono text-sm" />
        <div>
          <Button label="Run Query" icon="pi pi-play" :loading="running" @click="runQuery" />
        </div>

        <div v-if="preview" class="surface-ground border-round p-3">
          <div class="flex align-items-center gap-2 mb-3">
            <span class="font-semibold text-sm">Preview</span>
            <Tag :value="`${preview.total_rows.toLocaleString()} total rows`" severity="info" class="ml-auto" />
          </div>
          <DataTable :value="preview.rows" size="small" class="w-full mb-3">
            <Column v-for="col in preview.columns" :key="col" :field="col" :header="col" />
          </DataTable>
          <div class="flex flex-column gap-1">
            <label class="font-medium text-sm">Dataset Name</label>
            <InputText v-model="queryName" placeholder="e.g. RiskDB_PD_2024" class="w-full" />
          </div>
        </div>
      </div>

      <template #footer>
        <Button label="Cancel" severity="secondary" text @click="queryVisible = false" />
        <Button label="Save as Dataset" icon="pi pi-save" :disabled="!preview" @click="saveQuery" />
      </template>
    </Dialog>
  </div>
</template>
