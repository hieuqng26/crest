<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { datasets, addDataset, deleteDataset } from './datasetsStore'

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
const onDelete = (d) => {
  deleteDataset(d.id)
  toast.add({ severity: 'success', summary: 'Deleted', detail: d.name, life: 2000 })
}

// --- Upload dialog ---
const uploadVisible = ref(false)
const uploading = ref(false)
const uploaded = ref(null)

const openUpload = () => { uploaded.value = null; uploading.value = false; uploadVisible.value = true }

const onUpload = (event) => {
  uploading.value = true
  setTimeout(() => {
    uploading.value = false
    uploaded.value = {
      name: event.files[0].name,
      row_count: 12500,
      columns: ['obligor_id', 'default_flag', 'pd_estimate', 'lgd', 'ead', 'rating', 'sector', 'year']
    }
    toast.add({ severity: 'success', summary: 'Uploaded', detail: uploaded.value.name, life: 2500 })
  }, 1000)
}

const saveUpload = () => {
  if (!uploaded.value) return
  addDataset({
    name: uploaded.value.name,
    source: 'upload',
    row_count: uploaded.value.row_count,
    columns: uploaded.value.columns
  })
  toast.add({ severity: 'success', summary: 'Registered', detail: uploaded.value.name, life: 2500 })
  uploadVisible.value = false
}

// --- Live query dialog ---
const queryVisible = ref(false)
const sql = ref('SELECT obligor_id, default_flag, pd_estimate, lgd, ead, rating, sector, year\nFROM risk_db.dbo.pd_master\nWHERE year >= 2020')
const queryName = ref('')
const running = ref(false)
const preview = ref(null)

const openQuery = () => { preview.value = null; running.value = false; queryName.value = ''; queryVisible.value = true }

const runQuery = () => {
  running.value = true
  setTimeout(() => {
    running.value = false
    preview.value = {
      columns: ['obligor_id', 'default_flag', 'pd_estimate', 'lgd', 'ead', 'rating', 'sector', 'year'],
      rows: [
        { obligor_id: 'OB001', default_flag: 0, pd_estimate: 0.012, lgd: 0.45, ead: 1200000, rating: 'BBB', sector: 'Manufacturing', year: 2023 },
        { obligor_id: 'OB002', default_flag: 1, pd_estimate: 0.087, lgd: 0.60, ead: 450000,  rating: 'BB',  sector: 'Retail',         year: 2023 },
        { obligor_id: 'OB003', default_flag: 0, pd_estimate: 0.003, lgd: 0.40, ead: 3400000, rating: 'A',   sector: 'Finance',        year: 2022 }
      ],
      total_rows: 61203
    }
  }, 800)
}

const saveQuery = () => {
  if (!preview.value) {
    toast.add({ severity: 'warn', summary: 'Run the query first', life: 2500 }); return
  }
  if (!queryName.value.trim()) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Dataset name is required', life: 2500 }); return
  }
  addDataset({
    name: queryName.value.trim(),
    source: 'live_query',
    row_count: preview.value.total_rows,
    columns: preview.value.columns
  })
  toast.add({ severity: 'success', summary: 'Registered', detail: queryName.value, life: 2500 })
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
      <div class="flex flex-wrap align-items-center gap-3 mb-3">
        <IconField class="flex-1" style="min-width: 16rem">
          <InputIcon class="pi pi-search" />
          <InputText v-model="search" placeholder="Search datasets…" class="w-full" />
        </IconField>
        <SelectButton v-model="sourceFilter" :options="sourceOptions" optionLabel="label" optionValue="value" />
      </div>

      <DataTable :value="filtered" stripedRows size="small" :paginator="filtered.length > 10" :rows="10">
        <template #empty>
          <div class="text-center p-4 text-color-secondary">
            <i class="pi pi-inbox text-3xl block mb-2" />
            <p class="m-0">No datasets match your filters.</p>
          </div>
        </template>
        <Column field="id"   header="ID"   style="width:4rem" sortable />
        <Column field="name" header="Name" sortable />
        <Column field="source" header="Source" sortable>
          <template #body="{ data }">
            <Tag :value="data.source" :severity="sourceSeverity(data.source)" />
          </template>
        </Column>
        <Column field="row_count" header="Rows" sortable>
          <template #body="{ data }">{{ data.row_count.toLocaleString() }}</template>
        </Column>
        <Column field="created_by" header="Created By" sortable />
        <Column field="created_at" header="Date"        sortable />
        <Column field="status"     header="Status"      sortable>
          <template #body="{ data }">
            <Tag :value="data.status" :severity="statusSeverity(data.status)" />
          </template>
        </Column>
        <Column header="" style="width:8rem">
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

      <FileUpload
        name="dataset"
        accept=".csv,.xlsx,.parquet"
        :maxFileSize="104857600"
        :auto="true"
        :customUpload="true"
        @uploader="onUpload"
        chooseLabel="Choose file"
      >
        <template #empty>
          <div class="flex flex-column align-items-center gap-2 py-4 text-color-secondary">
            <i class="pi pi-cloud-upload text-4xl" />
            <span>Drag and drop a file here or click <b>Choose file</b></span>
          </div>
        </template>
      </FileUpload>

      <ProgressBar v-if="uploading" mode="indeterminate" class="mt-3" style="height:4px" />

      <div v-if="uploaded" class="surface-ground border-round p-4 mt-4">
        <div class="flex align-items-center gap-2 mb-3">
          <i class="pi pi-check-circle text-green-400 text-xl" />
          <span class="font-semibold">{{ uploaded.name }}</span>
          <Tag value="ready" severity="success" class="ml-auto" />
        </div>
        <div class="text-sm text-color-secondary mb-2">{{ uploaded.row_count.toLocaleString() }} rows detected</div>
        <div class="flex flex-wrap gap-2">
          <Chip v-for="col in uploaded.columns" :key="col" :label="col" class="text-xs" />
        </div>
      </div>

      <template #footer>
        <Button label="Cancel" severity="secondary" text @click="uploadVisible = false" />
        <Button label="Save to Registry" icon="pi pi-save" :disabled="!uploaded" @click="saveUpload" />
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
          <DataTable :value="preview.rows" size="small" stripedRows class="w-full mb-3">
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
