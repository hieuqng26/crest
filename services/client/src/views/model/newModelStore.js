// Shared state for the New Model wizard + its two sub-screens (Advanced Feature
// Selection, and the "Manage configurations" link back to Configurations) so
// navigating away and back doesn't lose in-progress form state.
import { ref, computed } from 'vue'
import modelConfigsAPI from '@/api/modelConfigsAPI'
import workflowsAPI from '@/api/workflowsAPI'

export const mode = ref('manual') // 'auto' | 'manual'

// Latest dataset per kind, resolved server-side — the wizard shows these
// read-only instead of offering a dataset picker.
export const resolvedDatasets = ref({ calibration: null, forecast: null, credit: null, financial_portfolio: null })
export const loadingDatasets = ref(false)

// Multiple targets can be trained in one launch.
export const targetCols = ref([])
export const selectedSectors = ref([])
export const availableSectors = ref([])
export const loadingSectors = ref(false)

export const configs = ref([])
export const registry = ref([])
export const selectedConfigId = ref(null)

// Default feature columns, applied to every target unless overridden.
export const featureCols = ref([])

// Per-target override: { [target]: { model_config_id, feature_cols } }
export const targetOverrides = ref({})
// Per-sector override (applies within every target): { [sector]: { model_config_id, feature_cols, split_by?, max_segments? } }
export const sectorOverrides = ref({})

export const modelName = ref('')
export const analysisParams = ref({ exposure: 1000000, discount_rate: 0.05, lifetime_horizon: 5, curve: 'moodys' })

const NUMERIC_DTYPE = /^(int|float|uint)/

function parseSchema(ds) {
  if (!ds) return { columns: [], dtypes: {} }
  const schema = ds.schema_json ? JSON.parse(ds.schema_json) : { columns: [], dtypes: {} }
  return { columns: schema.columns ?? [], dtypes: schema.dtypes ?? {} }
}

export const calibrationDataset = computed(() => {
  const ds = resolvedDatasets.value.calibration
  if (!ds) return null
  return { ...ds, ...parseSchema(ds) }
})
export const forecastDataset = computed(() => {
  const ds = resolvedDatasets.value.forecast
  if (!ds) return null
  return { ...ds, ...parseSchema(ds) }
})
export const creditDataset = computed(() => resolvedDatasets.value.credit)
export const financialDataset = computed(() => resolvedDatasets.value.financial_portfolio)

export const columnOptions = computed(() => calibrationDataset.value?.columns ?? [])
export const numericColumnOptions = computed(() =>
  columnOptions.value.filter((c) => NUMERIC_DTYPE.test(calibrationDataset.value?.dtypes?.[c] ?? ''))
)
const forecastColumnSet = computed(() => new Set(forecastDataset.value?.columns ?? []))

// Columns usable as a feature: numeric in the calibration dataset, present in
// the forecast dataset (so the auto-chained forecast stage can score it), and
// not itself one of the selected targets (leakage guard).
export const featureOptions = computed(() =>
  numericColumnOptions.value.filter((c) => !targetCols.value.includes(c) && forecastColumnSet.value.has(c))
)

export const selectedConfig = computed(() => configs.value.find((c) => c.id === selectedConfigId.value) || null)

export function objectiveFor(target) {
  const dt = calibrationDataset.value?.dtypes?.[target]
  if (!dt) return null
  return /^float/.test(dt) ? 'Regression' : 'Classification'
}

const REQUIRED_ANALYSIS_TARGETS = ['total_assets', 'total_shortterm_debts', 'total_longterm_debts']
export const analysisReady = computed(() =>
  REQUIRED_ANALYSIS_TARGETS.every((t) => targetCols.value.includes(t))
)
export const missingAnalysisTargets = computed(() =>
  REQUIRED_ANALYSIS_TARGETS.filter((t) => !targetCols.value.includes(t))
)
export const analysisDatasetsReady = computed(() => !!creditDataset.value)

export async function fetchResolvedDatasets() {
  loadingDatasets.value = true
  try {
    const { data } = await workflowsAPI.resolveDatasets()
    resolvedDatasets.value = data
  } finally {
    loadingDatasets.value = false
  }
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
    const datasetsAPI = (await import('@/api/datasetsAPI')).default
    const { data } = await datasetsAPI.sectors(datasetId)
    availableSectors.value = data.sectors || []
  } finally {
    loadingSectors.value = false
  }
}

export function resetNewModelForm() {
  mode.value = 'manual'
  targetCols.value = []
  selectedSectors.value = []
  selectedConfigId.value = null
  featureCols.value = []
  targetOverrides.value = {}
  sectorOverrides.value = {}
  modelName.value = ''
  analysisParams.value = { exposure: 1000000, discount_rate: 0.05, lifetime_horizon: 5, curve: 'moodys' }
}
