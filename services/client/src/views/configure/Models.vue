<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import { registry, fetchConfigs, addConfig, countByAlgorithm } from './configsStore'

const router = useRouter()
const toast = useToast()

const FAMILY_LABEL = { classification: 'Classification', timeseries: 'Time Series', statistical: 'Statistical' }
const FAMILY_SEVERITY = { classification: 'info', timeseries: 'warning', statistical: 'success' }
const FAMILY_ORDER = ['classification', 'timeseries', 'statistical']

onMounted(fetchConfigs)

const search = ref('')

const filteredRegistry = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return registry.value
  return registry.value.filter(a => a.algorithm.toLowerCase().includes(q))
})

const treeNodes = computed(() => {
  return FAMILY_ORDER
    .map(family => {
      const children = filteredRegistry.value
        .filter(a => a.family === family)
        .map(a => ({
          key: a.algorithm,
          label: a.algorithm,
          data: { type: 'algorithm', algorithm: a, count: countByAlgorithm(a.algorithm) }
        }))
      if (children.length === 0) return null
      return {
        key: `family:${family}`,
        label: FAMILY_LABEL[family],
        data: { type: 'family', family },
        children,
        selectable: false
      }
    })
    .filter(Boolean)
})

const expandedKeys = ref(FAMILY_ORDER.reduce((acc, f) => (acc[`family:${f}`] = true, acc), {}))
const selectedKey = ref({})
const selectedAlgorithm = computed(() => {
  const key = Object.keys(selectedKey.value)[0]
  return registry.value.find(a => a.algorithm === key) ?? registry.value[0] ?? null
})

// Once the registry loads, seed the default selection
watch(registry, (val) => {
  if (val.length && !Object.keys(selectedKey.value).length) {
    selectedKey.value = { [val[0].algorithm]: true }
  }
}, { immediate: true })

const drawerVisible = ref(false)
const form = ref({ name: '', target: '', features: '', hyperparams: {} })

const openDrawer = () => {
  form.value = {
    name: '',
    target: '',
    features: '',
    hyperparams: selectedAlgorithm.value.params.reduce((acc, p) => (acc[p.name] = p.default, acc), {})
  }
  drawerVisible.value = true
}

const saving = ref(false)
const saveConfig = async () => {
  if (!form.value.name.trim()) {
    toast.add({ severity: 'warn', summary: 'Validation', detail: 'Config name is required', life: 3000 })
    return
  }
  saving.value = true
  try {
    const { data } = await modelConfigsAPI.create({
      name: form.value.name,
      algorithm: selectedAlgorithm.value.algorithm,
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

const goToConfigurations = () =>
  router.push({ name: 'configurations', query: { algorithm: selectedAlgorithm.value.algorithm } })
</script>

<template>
  <div class="p-4 h-full flex flex-column">
    <div class="flex align-items-center justify-content-between mb-4">
      <div>
        <h2 class="text-2xl font-semibold m-0">Algorithm Catalog</h2>
        <p class="text-color-secondary text-sm m-0 mt-1">Browse available model families and their configurable parameters.</p>
      </div>
      <Button label="New Configuration" icon="pi pi-plus" size="small" @click="openDrawer" />
    </div>

    <div class="grid m-0 flex-1" style="min-height: 0">
      <!-- Left: tree -->
      <div class="col-12 md:col-4 lg:col-3 p-0 pr-3">
        <div class="surface-card border-round shadow-1 p-3 h-full flex flex-column">
          <IconField class="mb-3">
            <InputIcon class="pi pi-search" />
            <InputText v-model="search" placeholder="Search algorithms…" class="w-full" />
          </IconField>
          <Tree
            v-model:selectionKeys="selectedKey"
            v-model:expandedKeys="expandedKeys"
            :value="treeNodes"
            selectionMode="single"
            class="border-none p-0 flex-1 overflow-auto"
          >
            <template #default="{ node }">
              <div class="flex align-items-center gap-2 w-full">
                <span class="text-sm">{{ node.label }}</span>
                <Tag
                  v-if="node.data?.type === 'algorithm' && node.data.count > 0"
                  :value="node.data.count"
                  severity="secondary"
                  class="ml-auto text-xs"
                />
              </div>
            </template>
          </Tree>
        </div>
      </div>

      <!-- Right: detail -->
      <div class="col-12 md:col-8 lg:col-9 p-0">
        <div v-if="!selectedAlgorithm" class="surface-card border-round shadow-1 p-4 h-full flex align-items-center justify-content-center text-color-secondary">
          <i class="pi pi-spin pi-spinner text-2xl mr-2" /> Loading catalog…
        </div>
        <div v-else class="surface-card border-round shadow-1 p-4 h-full flex flex-column gap-4 overflow-auto">
          <div>
            <div class="flex align-items-center gap-2 mb-1">
              <h3 class="text-xl font-semibold m-0">{{ selectedAlgorithm.algorithm }}</h3>
              <Tag :value="FAMILY_LABEL[selectedAlgorithm.family]" :severity="FAMILY_SEVERITY[selectedAlgorithm.family]" class="text-xs" />
              <span v-if="countByAlgorithm(selectedAlgorithm.algorithm)" class="text-xs text-color-secondary ml-2">
                {{ countByAlgorithm(selectedAlgorithm.algorithm) }} saved configuration{{ countByAlgorithm(selectedAlgorithm.algorithm) === 1 ? '' : 's' }}
              </span>
            </div>
            <p class="text-color-secondary text-sm m-0">{{ selectedAlgorithm.description }}</p>
          </div>

          <div>
            <h4 class="text-sm font-semibold text-color-secondary uppercase mb-2 m-0">Parameters</h4>
            <DataTable :value="selectedAlgorithm.params" size="small" stripedRows class="text-sm">
              <Column field="name" header="Name">
                <template #body="{ data }"><span class="font-mono text-primary">{{ data.name }}</span></template>
              </Column>
              <Column field="type" header="Type" style="width:7rem">
                <template #body="{ data }"><Tag :value="data.type" severity="secondary" class="text-xs" /></template>
              </Column>
              <Column header="Default" style="width:8rem">
                <template #body="{ data }">
                  <span class="font-mono text-xs">{{ data.default === null ? 'null' : String(data.default) }}</span>
                </template>
              </Column>
              <Column field="description" header="Description" />
            </DataTable>
          </div>

          <div class="flex gap-2">
            <Button
              label="View saved configurations"
              icon="pi pi-list"
              size="small"
              text
              :disabled="!countByAlgorithm(selectedAlgorithm.algorithm)"
              @click="goToConfigurations"
            />
          </div>
        </div><!-- end v-else detail panel -->
      </div>
    </div>

    <Dialog v-model:visible="drawerVisible" modal :style="{ width: '32rem' }" :draggable="false">
      <template #header>
        <div>
          <div class="text-xs text-color-secondary">New configuration for</div>
          <div class="text-lg font-semibold flex align-items-center gap-2">
            {{ selectedAlgorithm.algorithm }}
            <Tag :value="FAMILY_LABEL[selectedAlgorithm.family]" :severity="FAMILY_SEVERITY[selectedAlgorithm.family]" class="text-xs" />
          </div>
        </div>
      </template>

      <div class="flex flex-column gap-4">
        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Config Name</label>
          <InputText v-model="form.name" placeholder="e.g. PD_LR_2024_Q4" class="w-full" />
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Target Column</label>
          <InputText v-model="form.target" placeholder="e.g. default_flag" class="w-full" />
        </div>

        <div class="flex flex-column gap-1">
          <label class="font-medium text-sm">Feature Columns <span class="text-color-secondary font-normal">(comma-separated)</span></label>
          <Textarea v-model="form.features" rows="2" placeholder="e.g. pd_estimate, lgd, ead, rating, sector" class="w-full" />
        </div>

        <div class="flex flex-column gap-2">
          <label class="font-medium text-sm">Hyperparameters</label>
          <div v-for="p in selectedAlgorithm.params" :key="p.name" class="flex flex-column gap-1">
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
