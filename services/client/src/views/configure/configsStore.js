import { ref } from 'vue'
import modelConfigsAPI from '@/api/modelConfigsAPI'

export const configs  = ref([])
export const registry = ref([])
export const loading  = ref(false)

export const fetchConfigs = async () => {
  loading.value = true
  try {
    const [cfgRes, regRes] = await Promise.all([
      modelConfigsAPI.list(),
      modelConfigsAPI.registry()
    ])
    configs.value  = cfgRes.data
    registry.value = regRes.data
  } finally {
    loading.value = false
  }
}

export const addConfig = (cfg) => {
  configs.value = [cfg, ...configs.value]
}

export const duplicateConfig = async (cfg) => {
  const body = {
    name: `${cfg.name} (copy)`,
    algorithm: cfg.algorithm,
    hyperparams: cfg.hyperparams_json ? JSON.parse(cfg.hyperparams_json) : {},
    feature_cols: cfg.feature_cols_json ? JSON.parse(cfg.feature_cols_json) : [],
    target_col: cfg.target_col
  }
  const { data } = await modelConfigsAPI.create(body)
  addConfig(data)
  return data
}

export const deleteConfig = async (id) => {
  // No backend DELETE endpoint yet — remove from local list only until Phase 4 backend adds it
  configs.value = configs.value.filter(c => c.id !== id)
}

export const countByAlgorithm = (algorithm) =>
  configs.value.filter(c => c.algorithm === algorithm).length

export const getConfig = (id) =>
  configs.value.find(c => c.id === Number(id) || c.id === id) ?? null

