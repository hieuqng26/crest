import { ref } from 'vue'

export const configs = ref([
  { id: 1, name: 'PD_LR_2024_Q4',  algorithm: 'LogisticRegression', target_col: 'default_flag', created_by: 'analyst@bank.com', created_at: '2026-06-10' },
  { id: 2, name: 'LGD_GBM_Corp',   algorithm: 'GradientBoosting',   target_col: 'lgd',          created_by: 'analyst@bank.com', created_at: '2026-06-09' },
  { id: 3, name: 'Macro_ARIMA_Q3', algorithm: 'ARIMA',              target_col: 'gdp_growth',   created_by: 'quant@bank.com',   created_at: '2026-06-08' },
  { id: 4, name: 'PD_GLM_Retail',  algorithm: 'GLM_Binomial',       target_col: 'default_flag', created_by: 'risk@bank.com',    created_at: '2026-06-07' }
])

const nextId = () => configs.value.reduce((m, c) => Math.max(m, c.id), 0) + 1
const today  = () => new Date().toISOString().slice(0, 10)

export const addConfig = ({ name, algorithm, target_col }) => {
  const row = {
    id: nextId(),
    name: name.trim(),
    algorithm,
    target_col: target_col || '—',
    created_by: 'you@bank.com',
    created_at: today()
  }
  configs.value.push(row)
  return row
}

export const duplicateConfig = (cfg) => {
  const row = { ...cfg, id: nextId(), name: `${cfg.name}_copy`, created_at: today() }
  configs.value.push(row)
  return row
}

export const deleteConfig = (id) => {
  configs.value = configs.value.filter(c => c.id !== id)
}

export const countByAlgorithm = (algorithm) =>
  configs.value.filter(c => c.algorithm === algorithm).length

export const configsForAlgorithm = (algorithm) =>
  configs.value.filter(c => c.algorithm === algorithm)
