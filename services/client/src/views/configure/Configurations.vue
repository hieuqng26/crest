<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { FilterMatchMode } from 'primevue/api'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import { configs, registry, fetchConfigs, addConfig, duplicateConfig, deleteConfig } from './configsStore'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const FAMILY_LABEL = { classification: 'Classification', timeseries: 'Time Series', statistical: 'Statistical' }
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
    (!familyFilter.value || algoFamily(c.algorithm) === familyFilter.value)
  )
)

// Drawer
const drawerVisible = ref(false)
const form = ref({ name: '', algorithm: null, target: '', features: '', hyperparams: {} })
const selectedAlgoMeta = computed(() =>
  registry.value.find(a => a.algorithm === form.value.algorithm) || null
)

watch(() => form.value.algorithm, (algo) => {
  const meta = registry.value.find(a => a.algorithm === algo)
  form.value.hyperparams = meta
    ? meta.params.reduce((acc, p) => (acc[p.name] = p.default, acc), {})
    : {}
})

const openDrawer = (presetAlgorithm = null) => {
  form.value = {
    name: '',
    algorithm: presetAlgorithm || algorithmFilter.value || null,
    target: '',
    features: '',
    hyperparams: {}
  }
  drawerVisible.value = true
}

const saving = ref(false)
const saveConfig = async () => {
  if (!form.value.name.trim()) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Config name is required', life: 3000 })
    return
  }
  if (!form.value.algorithm) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Algorithm is required', life: 3000 })
    return
  }
  saving.value = true
  try {
    const { data } = await modelConfigsAPI.create({
      name: form.value.name,
      algorithm: form.value.algorithm,
      target_col: form.value.target,
      feature_cols: form.value.features ? form.value.features.split(',').map(s => s.trim()).filter(Boolean) : [],
      hyperparams: form.value.hyperparams
    })
    addConfig(data)
    toast.add({ severity: 'success', summary: 'Saved', detail: `Config "${data.name}" created`, life: 2500 })
    drawerVisible.value = false
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Save failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    saving.value = false
  }
}

const calibrate = (cfg) => router.push({ name: 'calibrate_new', query: { config_id: cfg.id } })
const onDuplicate = async (cfg) => {
  const row = await duplicateConfig(cfg)
  toast.add({ severity: 'info', summary: 'Duplicated', detail: row.name, life: 2000 })
}
const onDelete = (cfg) => {
  deleteConfig(cfg.id)
  toast.add({ severity: 'success', summary: 'Deleted', detail: cfg.name, life: 2000 })
}

onMounted(() => {
  if (route.query.new === '1') openDrawer(route.query.algorithm || null)
})
</script>

<template>
  <div class="p-4">
    <div class="flex align-items-center justify-content-between mb-4">
      <div>
        <h2 class="text-2xl font-semibold m-0">Saved Configurations</h2>
        <p class="text-color-secondary text-sm m-0 mt-1">Model configurations ready to calibrate.</p>
      </div>
      <Button label="New Configuration" icon="pi pi-plus" size="small" @click="openDrawer()" />
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
        <SelectButton v-model="familyFilter" :options="familyOptions" optionLabel="label" optionValue="value" />
      </div>

      <DataTable
        :value="filteredRows"
        v-model:filters="filters"
        :globalFilterFields="['name', 'algorithm', 'target_col', 'created_by']"
        stripedRows
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
        <Column field="created_at" header="Date" sortable style="width:8rem" />
        <Column header="" style="width:10rem">
          <template #body="{ data }">
            <div class="flex gap-1 justify-content-end">
              <Button icon="pi pi-play"  text rounded size="small" v-tooltip.top="'Calibrate'" @click="calibrate(data)" />
              <Button icon="pi pi-copy"  text rounded size="small" v-tooltip.top="'Duplicate'" @click="onDuplicate(data)" />
              <Button icon="pi pi-trash" text rounded size="small" severity="danger" v-tooltip.top="'Delete'" @click="onDelete(data)" />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <Dialog v-model:visible="drawerVisible" modal :style="{ width: '32rem' }" :draggable="false">
      <template #header>
        <div class="text-lg font-semibold">New Configuration</div>
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
        <Button label="Cancel" severity="secondary" text @click="drawerVisible = false" />
        <Button label="Save Configuration" icon="pi pi-save" @click="saveConfig" />
      </template>
    </Dialog>
  </div>
</template>
