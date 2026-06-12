import { ref } from 'vue'
import seed from './mock/datasets.json'

const DEFAULT_COLUMNS = {
  'PD_2024_Q4.csv':           ['obligor_id', 'default_flag', 'pd_estimate', 'lgd', 'ead', 'rating', 'sector', 'year'],
  'MacroFactors_Q3.parquet':  ['period', 'gdp_growth', 'unemployment', 'inflation', 'policy_rate', 'fx_usd'],
  'LGD_Corp_2023.xlsx':       ['obligor_id', 'facility_id', 'lgd', 'recovery_rate', 'collateral_type', 'seniority'],
  'RiskDB_PD_Retail_Live':    ['customer_id', 'default_flag', 'pd_estimate', 'product', 'tenure_months', 'region'],
  'MacroFactors_Q2.parquet':  ['period', 'gdp_growth', 'unemployment', 'inflation', 'policy_rate', 'fx_usd']
}

export const datasets = ref(
  seed.map(d => ({ ...d, columns: DEFAULT_COLUMNS[d.name] || ['col_1', 'col_2', 'col_3'] }))
)

const nextId = () => datasets.value.reduce((m, d) => Math.max(m, d.id), 0) + 1
const today  = () => new Date().toISOString().slice(0, 16).replace('T', ' ')

export const addDataset = ({ name, source, row_count, columns, created_by = 'you@bank.com' }) => {
  const row = {
    id: nextId(),
    name,
    source,
    row_count: row_count ?? 0,
    status: 'ready',
    created_by,
    created_at: today(),
    columns: columns && columns.length ? columns : ['col_1', 'col_2', 'col_3']
  }
  datasets.value.unshift(row)
  return row
}

export const deleteDataset = (id) => {
  datasets.value = datasets.value.filter(d => d.id !== id)
}

export const getDataset = (id) => {
  const numId = typeof id === 'string' ? Number(id) : id
  return datasets.value.find(d => d.id === numId) || null
}
