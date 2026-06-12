import { ref } from 'vue'
import datasetsAPI from '@/api/datasetsAPI'

export const datasets   = ref([])
export const loading    = ref(false)
export const lastError  = ref(null)

export const fetchDatasets = async () => {
  loading.value = true
  lastError.value = null
  try {
    const { data } = await datasetsAPI.list()
    datasets.value = data.map(d => ({
      ...d,
      columns: d.schema_json ? JSON.parse(d.schema_json).columns ?? [] : []
    }))
  } catch (e) {
    lastError.value = e?.response?.data?.error ?? e.message
  } finally {
    loading.value = false
  }
}

export const addDataset = (ds) => {
  const withCols = {
    ...ds,
    columns: ds.schema_json ? JSON.parse(ds.schema_json).columns ?? [] : (ds.columns ?? [])
  }
  datasets.value = [withCols, ...datasets.value]
}

export const deleteDataset = async (id) => {
  await datasetsAPI.delete(id)
  datasets.value = datasets.value.filter(d => d.id !== id)
}

export const getDataset = (id) =>
  datasets.value.find(d => d.id === Number(id) || d.id === id) ?? null
