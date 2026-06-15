<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { FilterMatchMode } from 'primevue/api'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import { configs, registry, fetchConfigs, addConfig, updateConfig, duplicateConfig, deleteConfig, bulkDeleteConfigs } from './configsStore'
import { fmtDate } from '@/utils/datetime'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const FAMILY_LABEL    = { classification: 'Classification', timeseries: 'Time Series', statistical: 'Statistical' }
const FAMILY_SEVERITY = { classification: 'info', timeseries: 'warning', statistical: 'success' }

const algorithmOptions = computed(() => [
  { label: 'All algorithms', value: null },
  ...registry.value.map(a => ({ label: `${a.algorithm} (${FAMILY_LABEL[a.family]})`, value: a.algorithm }))
])
const familyOptions = [
  { label: 'All',            value: null },
  { label: 'Classification', value: 'classification' },
  { label: 'Time Series',    value: 'timeseries' },
  { label: 'Statistical',    value: 'statistical' }
]

onMounted(fetchConfigs)

const algorithmFilter = ref(route.query.algorithm || null)
const familyFilter = ref(null)
const filters = ref({ global: { value: '', matchMode: FilterMatchMode.CONTAINS } })

const algoFamily = (algoName) => registry.value.find(a => a.algorithm === algoName)?.family

const filteredRows = computed(() =>
  configs.value.filter(c =>
    (!algorithmFilter.value || c.algorithm === algorithmFilter.value) &&
    (!familyFilter.value || algoFamily(c.algorithm) === familyFilter.value) &&
    (!filters.value.global.value ||
      ['name', 'algorithm', 'target_col', 'created_by'].some(f =>
        String(c[f] ?? '').toLowerCase().includes(filters.value.global.value.toLowerCase())
      )
    )
  )
)

// ---- Dialog (create + edit) ----
const dialogVisible = ref(false)
const editingId = ref(null)
const form = ref({ name: '', algorithm: null, target: '', features: '', hyperparams: {} })
const saving = ref(false)

const selectedAlgoMeta = computed(() =>
  registry.value.find(a => a.algorithm === form.value.algorithm) || null
)

watch(() => form.value.algorithm, (algo, prev) => {
  if (algo === prev) return
  const meta = registry.value.find(a => a.algorithm === algo)
  form.value.hyperparams = meta
    ? meta.params.reduce((acc, p) => (acc[p.name] = p.default, acc), {})
    : {}
})

const openCreate = (presetAlgorithm = null) => {
  editingId.value = null
  form.value = {
    name: '',
    algorithm: presetAlgorithm || algorithmFilter.value || null,
    target: '',
    features: '',
    hyperparams: {}
  }
  dialogVisible.value = true
}

const openEdit = (cfg) => {
  editingId.value = cfg.id
  const params = cfg.hyperparams_json ? JSON.parse(cfg.hyperparams_json) : {}
  const featureCols = cfg.feature_cols_json ? JSON.parse(cfg.feature_cols_json) : []
  form.value = {
    name: cfg.name,
    algorithm: cfg.algorithm,
    target: cfg.target_col ?? '',
    features: featureCols.join(', '),
    hyperparams: params
  }
  dialogVisible.value = true
}

const saveConfig = async () => {
  if (!form.value.name.trim()) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Config name is required', life: 3000 }); return
  }
  if (!form.value.algorithm) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Algorithm is required', life: 3000 }); return
  }
  saving.value = true
  const body = {
    name: form.value.name,
    algorithm: form.value.algorithm,
    target_col: form.value.target,
    feature_cols: form.value.features ? form.value.features.split(',').map(s => s.trim()).filter(Boolean) : [],
    hyperparams: form.value.hyperparams
  }
  try {
    if (editingId.value) {
      const data = await updateConfig(editingId.value, body)
      toast.add({ severity: 'success', summary: 'Updated', detail: `"${data.name}" saved`, life: 2500 })
    } else {
      const { data } = await modelConfigsAPI.create(body)
      addConfig(data)
      toast.add({ severity: 'success', summary: 'Created', detail: `"${data.name}" saved`, life: 2500 })
    }
    dialogVisible.value = false
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Save failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    saving.value = false
  }
}

// ---- Row actions ----
const calibrate = (cfg) => router.push({ name: 'calibrate_new', query: { config_id: cfg.id } })

const onDuplicate = async (cfg) => {
  const row = await duplicateConfig(cfg)
  toast.add({ severity: 'info', summary: 'Duplicated', detail: row.name, life: 2000 })
}

const onDelete = async (cfg) => {
  try {
    await deleteConfig(cfg.id)
    toast.add({ severity: 'success', summary: 'Deleted', detail: cfg.name, life: 2000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
}

// ---- Bulk delete ----
const selectMode = ref(false)
const selection = ref([])
const confirmingBulkDelete = ref(false)

const exitSelectMode = () => {
  selectMode.value = false
  selection.value = []
  confirmingBulkDelete.value = false
}

const bulkDelete = async () => {
  try {
    const data = await bulkDeleteConfigs(selection.value.map(c => c.id))
    toast.add({ severity: 'success', summary: 'Deleted', detail: `${data.deleted} configuration${data.deleted !== 1 ? 's' : ''} deleted`, life: 3000 })
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Delete failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  }
  exitSelectMode()
}

onMounted(() => {
  if (route.query.new === '1') openCreate(route.query.algorithm || null)
})
</script>

<template>
  <div class="p-4">
    <div class="flex align-items-center justify-content-between mb-4">
      <div>
        <h2 class="text-2xl font-semibold m-0">Saved Configurations</h2>
        <p class="text-color-secondary text-sm m-0 mt-1">Model configurations ready to calibrate.</p>
      </div>
    </div>

    <div class="surface-card border-round shadow-1 p-4">
      <div class="flex flex-wrap align-items-center gap-3 mb-3">
        <IconField class="flex-1" style="min-width: 16rem">
          <InputIcon class="pi pi-search" />
          <InputText v-model="filters.global.value" placeholder="Search configurations…" class="w-full" />
        </IconField>
        <Dropdown
          v-model="algorithmFilter"
          :options="algorithmOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="Algorithm"
          class="w-15rem"
          showClear
        />
        <Dropdown
          v-model="familyFilter"
          :options="familyOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="All families"
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
            <span class="text-sm font-medium text-red-400">Delete {{ selection.length }} config{{ selection.length !== 1 ? 's' : '' }}?</span>
            <Button label="Confirm" icon="pi pi-check" size="small" severity="danger" @click="bulkDelete" />
            <Button label="Cancel"  size="small" severity="secondary" text @click="confirmingBulkDelete = false" />
          </template>
          <Button icon="pi pi-times" size="small" severity="secondary" text rounded @click="exitSelectMode" v-tooltip.top="'Exit select mode'" />
        </template>
      </div>

      <DataTable
        :value="filteredRows"
        v-model:selection="selection"
        :selectionMode="selectMode ? 'multiple' : null"
        dataKey="id"
        size="small"
        :paginator="filteredRows.length > 10"
        :rows="10"
      >
        <template #empty>
          <div class="text-center p-4 text-color-secondary">
            <i class="pi pi-inbox text-3xl block mb-2" />
            <p class="m-0">No configurations match your filters.</p>
          </div>
        </template>

        <Column v-if="selectMode" selectionMode="multiple" style="width: 3rem" />
        <Column field="id" header="ID" style="width:4rem" />
        <Column field="name" header="Name" sortable />
        <Column header="Algorithm" sortable sortField="algorithm">
          <template #body="{ data }">
            <div class="flex align-items-center gap-2">
              <span class="font-mono text-xs">{{ data.algorithm }}</span>
              <Tag
                v-if="algoFamily(data.algorithm)"
                :value="FAMILY_LABEL[algoFamily(data.algorithm)]"
                :severity="FAMILY_SEVERITY[algoFamily(data.algorithm)]"
                class="text-xs"
              />
            </div>
          </template>
        </Column>
        <Column field="target_col" header="Target" sortable />
        <Column field="created_by" header="Created By" sortable />
        <Column field="created_at" header="Date" sortable style="width:12rem">
          <template #body="{ data }">{{ fmtDate(data.created_at) }}</template>
        </Column>
        <Column v-if="!selectMode" header="" style="width:12rem">
          <template #body="{ data }">
            <div class="flex gap-1 justify-content-end">
              <Button icon="pi pi-play"         text rounded size="small" v-tooltip.top="'Calibrate'" @click="calibrate(data)" />
              <Button icon="pi pi-pencil"        text rounded size="small" v-tooltip.top="'Edit'"      @click="openEdit(data)" />
              <Button icon="pi pi-copy"          text rounded size="small" v-tooltip.top="'Duplicate'" @click="onDuplicate(data)" />
              <Button icon="pi pi-trash"         text rounded size="small" severity="danger" v-tooltip.top="'Delete'" @click="onDelete(data)" />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <!-- Create / Edit dialog -->
    <Dialog v-model:visible="dialogVisible" modal :style="{ width: '32rem' }" :draggable="false">
      <template #header>
        <div class="text-lg font-semibold">{{ editingId ? 'Edit Configuration' : 'New Configuration' }}</div>
      </template>

      <div class="flex flex-column gap-4">
        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Config Name</label>
          <InputText v-model="form.name" placeholder="e.g. PD_LR_2024_Q4" class="w-full" />
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Algorithm</label>
          <Dropdown
            v-model="form.algorithm"
            :options="algorithmOptions.filter(o => o.value)"
            optionLabel="label"
            optionValue="value"
            placeholder="Select algorithm"
            class="w-full"
            :disabled="!!editingId"
          />
          <span v-if="selectedAlgoMeta" class="text-xs text-color-secondary mt-1">{{ selectedAlgoMeta.description }}</span>
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Target Column</label>
          <InputText v-model="form.target" placeholder="e.g. default_flag" class="w-full" />
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Feature Columns <span class="text-color-secondary font-normal">(comma-separated)</span></label>
          <Textarea v-model="form.features" rows="2" placeholder="e.g. pd_estimate, lgd, ead, rating, sector" class="w-full" />
        </div>

        <div v-if="selectedAlgoMeta" class="flex flex-column gap-2">
          <label class="font-medium text-sm">Hyperparameters</label>
          <div v-for="p in selectedAlgoMeta.params" :key="p.name" class="flex flex-column gap-1">
            <div class="flex align-items-center justify-content-between">
              <span class="font-mono text-xs text-primary">{{ p.name }}</span>
              <span class="text-xs text-color-secondary">{{ p.type }}</span>
            </div>
            <InputText
              v-if="p.type === 'string'"
              v-model="form.hyperparams[p.name]"
              class="w-full"
              :placeholder="String(p.default)"
            />
            <InputNumber
              v-else-if="p.type === 'float' || p.type === 'int'"
              v-model="form.hyperparams[p.name]"
              :useGrouping="false"
              :minFractionDigits="p.type === 'float' ? 1 : 0"
              :maxFractionDigits="p.type === 'float' ? 6 : 0"
              class="w-full"
              fluid
            />
            <InputSwitch v-else-if="p.type === 'bool'" v-model="form.hyperparams[p.name]" />
            <span v-if="p.description" class="text-xs text-color-secondary">{{ p.description }}</span>
          </div>
        </div>
      </div>

      <template #footer>
        <Button label="Cancel" severity="secondary" text @click="dialogVisible = false" />
        <Button
          :label="editingId ? 'Save Changes' : 'Save Configuration'"
          icon="pi pi-save"
          :loading="saving"
          @click="saveConfig"
        />
      </template>
    </Dialog>
  </div>
</template>
