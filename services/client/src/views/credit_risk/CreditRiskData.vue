<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import datasetsAPI from '@/api/datasetsAPI'
import { fmtDate } from '@/utils/datetime'

const router = useRouter()
const toast  = useToast()

const datasets   = ref([])
const loading    = ref(false)
const search     = ref('')

const filtered = computed(() =>
  datasets.value.filter(d => d.name.toLowerCase().includes(search.value.toLowerCase()))
)

const statusSeverity = (s) => ({ ready: 'success', processing: 'warning', error: 'danger' }[s] ?? 'secondary')

async function fetchDatasets() {
  loading.value = true
  try {
    const { data } = await datasetsAPI.listByKind('credit')
    datasets.value = data
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Failed to load', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    loading.value = false
  }
}

onMounted(fetchDatasets)

// ── upload ────────────────────────────────────────────────────────────────────
const uploadVisible = ref(false)
const uploading     = ref(false)
const uploadFile    = ref(null)
const uploadName    = ref('')

const openUpload = () => {
  uploadFile.value = null
  uploadName.value = ''
  uploading.value  = false
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
    const { data } = await datasetsAPI.uploadCredit(uploadFile.value, uploadName.value.trim())
    datasets.value.unshift(data)
    toast.add({ severity: 'success', summary: 'Uploaded', detail: data.name, life: 2500 })
    uploadVisible.value = false
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Upload failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    uploading.value = false
  }
}

// ── delete ────────────────────────────────────────────────────────────────────
const onDelete = async (d) => {
  try {
    await datasetsAPI.delete(d.id)
    datasets.value = datasets.value.filter(x => x.id !== d.id)
    toast.add({ severity: 'success', summary: 'Deleted', detail: d.name, life: 2000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}
</script>

<template>
  <div class="p-4">
    <div class="flex align-items-center justify-content-between mb-4">
      <div>
        <h2 class="text-2xl font-semibold m-0">Credit Data</h2>
        <p class="text-color-secondary text-sm m-0 mt-1">Datasets used for credit risk analysis (KMV / ECL).</p>
      </div>
      <Button label="Upload" icon="pi pi-upload" size="small" @click="openUpload" />
    </div>

    <div class="surface-card border-round shadow-1 p-4">
      <div class="flex align-items-center gap-3 mb-3">
        <IconField class="flex-1" style="min-width: 16rem">
          <InputIcon class="pi pi-search" />
          <InputText v-model="search" placeholder="Search datasets…" class="w-full" />
        </IconField>
      </div>

      <DataTable :value="filtered" size="small" :loading="loading">
        <template #empty>
          <div class="text-center p-5 text-color-secondary">
            <i class="pi pi-database text-3xl block mb-2" />
            <p class="m-0">No credit datasets yet. Upload one to get started.</p>
          </div>
        </template>

        <Column field="id"         header="ID"         style="width:4rem" sortable />
        <Column field="name"       header="Name"       sortable />
        <Column field="row_count"  header="Rows"       sortable>
          <template #body="{ data }">{{ data.row_count?.toLocaleString() }}</template>
        </Column>
        <Column field="created_by" header="Created By" sortable />
        <Column field="created_at" header="Date"       sortable>
          <template #body="{ data }">{{ fmtDate(data.created_at) }}</template>
        </Column>
        <Column field="status"     header="Status"     sortable>
          <template #body="{ data }">
            <Tag :value="data.status" :severity="statusSeverity(data.status)" />
          </template>
        </Column>
        <Column header="" style="width:7rem">
          <template #body="{ data }">
            <Button icon="pi pi-eye" text rounded size="small" v-tooltip.top="'View'" @click="router.push({ name: 'dataset_view', params: { id: data.id }, query: { back: 'credit_risk_data' } })" />
            <Button icon="pi pi-trash" text rounded size="small" severity="danger" v-tooltip.top="'Delete'" @click="onDelete(data)" />
          </template>
        </Column>
      </DataTable>
    </div>

    <!-- Upload dialog -->
    <Dialog v-model:visible="uploadVisible" modal :style="{ width: '36rem' }" :draggable="false">
      <template #header>
        <div>
          <div class="text-lg font-semibold">Upload Credit Dataset</div>
          <div class="text-xs text-color-secondary">CSV, Excel, or Parquet with client_id, market_cap, vol_equity, risk_free_rate, rating columns</div>
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
          <InputText v-model="uploadName" placeholder="e.g. CreditPortfolio_2024" class="w-full" />
        </div>
      </div>

      <ProgressBar v-if="uploading" mode="indeterminate" class="mt-3" style="height:4px" />

      <template #footer>
        <Button label="Cancel" severity="secondary" text @click="uploadVisible = false" />
        <Button label="Upload & Register" icon="pi pi-upload" :loading="uploading" :disabled="!uploadFile || !uploadName.trim()" @click="saveUpload" />
      </template>
    </Dialog>

    <Toast />
  </div>
</template>
