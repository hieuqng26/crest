// Shared state for the New Model wizard + its two sub-screens (Advanced Feature
// Selection, and the "Manage configurations" link back to Configurations) so
// navigating away and back doesn't lose in-progress form state.
import { ref, computed } from 'vue'
import datasetsAPI from '@/api/datasetsAPI'
import modelConfigsAPI from '@/api/modelConfigsAPI'

export const mode = ref('manual') // 'auto' | 'manual'

export const datasets = ref([])
export const selectedDatasetId = ref(null)
export const targetCol = ref(null)
export const selectedSectors = ref([])
export const availableSectors = ref([])
export const loadingSectors = ref(false)

export const configs = ref([])
export const registry = ref([])
export const selectedConfigId = ref(null)

// Explicit list of selected feature columns. Empty means "not loaded yet" —
// once a target is chosen this is seeded to all non-target columns (matching
// the mockup's default "10/10 selected" state) and the user unchecks from there.
export const featureCols = ref([])

// Per-sector override: { [sector]: { model_config_id, feature_cols } }
export const sectorOverrides = ref({})

export const modelName = ref('')

export const selectedDataset = computed(() => datasets.value.find((d) => d.id === selectedDatasetId.value) || null)
export const columnOptions = computed(() => selectedDataset.value?.columns ?? [])
export const featureOptions = computed(() => columnOptions.value.filter((c) => c !== targetCol.value))
export const selectedConfig = computed(() => configs.value.find((c) => c.id === selectedConfigId.value) || null)
export const targetDtype = computed(() => selectedDataset.value?.dtypes?.[targetCol.value] ?? null)
export const objectiveLabel = computed(() => {
  const dt = targetDtype.value
  if (!dt) return null
  return /^float/.test(dt) ? 'Regression' : 'Classification'
})

export async function fetchDatasets() {
  const { data } = await datasetsAPI.list()
  datasets.value = (data ?? [])
    .filter((d) => d.kind === 'calibration')
    .map((d) => {
      const schema = d.schema_json ? JSON.parse(d.schema_json) : { columns: [], dtypes: {} }
      return { ...d, columns: schema.columns ?? [], dtypes: schema.dtypes ?? {} }
    })
}

export async function fetchConfigs() {
  const [cfgRes, regRes] = await Promise.all([modelConfigsAPI.list(), modelConfigsAPI.registry()])
  configs.value = cfgRes.data ?? []
  registry.value = regRes.data ?? []
}

export async function fetchSectors(datasetId) {
  availableSectors.value = []
  if (!datasetId) return
  loadingSectors.value = true
  try {
    const { data } = await datasetsAPI.sectors(datasetId)
    availableSectors.value = data.sectors || []
  } finally {
    loadingSectors.value = false
  }
}

export function resetNewModelForm() {
  mode.value = 'manual'
  selectedDatasetId.value = null
  targetCol.value = null
  selectedSectors.value = []
  selectedConfigId.value = null
  featureCols.value = []
  sectorOverrides.value = {}
  modelName.value = ''
}
