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
    hyperparams: cfg.hyperparams_json ? JSON.parse(cfg.hyperparams_json) : {}
  }
  const { data } = await modelConfigsAPI.create(body)
  addConfig(data)
  return data
}

export const updateConfig = async (id, body) => {
  const { data } = await modelConfigsAPI.update(id, body)
  configs.value = configs.value.map(c => c.id === id ? data : c)
  return data
}

export const deleteConfig = async (id) => {
  await modelConfigsAPI.delete(id)
  configs.value = configs.value.filter(c => c.id !== id)
}

export const bulkDeleteConfigs = async (ids) => {
  const { data } = await modelConfigsAPI.bulkDelete(ids)
  const deletedSet = new Set(ids)
  configs.value = configs.value.filter(c => !deletedSet.has(c.id))
  return data
}

export const countByAlgorithm = (algorithm) =>
  configs.value.filter(c => c.algorithm === algorithm).length

export const getConfig = (id) =>
  configs.value.find(c => c.id === Number(id) || c.id === id) ?? null

