import { httpClient } from './httpClient'
import { toPageParams } from '@/utils/tablePaging'

const datasetsAPI = {
  list:        ()       => httpClient.get('/datasets/'),
  listByKind:  (kind)   => httpClient.get('/datasets/', { params: { kind } }),
  get:         (id)     => httpClient.get(`/datasets/${id}`),
  delete:      (id)     => httpClient.delete(`/datasets/${id}`),
  bulkDelete:  (ids)    => httpClient.post('/datasets/bulk-delete', { ids }),

  upload: (file, name, description = '', kind = 'calibration') => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('name', name)
    fd.append('description', description)
    fd.append('kind', kind)
    return httpClient.post('/datasets/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  uploadCredit: (file, name) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('name', name)
    fd.append('kind', 'credit')
    return httpClient.post('/datasets/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  query: (sql, name, description = '') =>
    httpClient.post('/datasets/query', { sql, name, description }),

  sectors: (id) => httpClient.get(`/datasets/${id}/sectors`),

  // Rows endpoint — used by DatasetView via CommonDataTable's fetchPage
  // GET /api/datasets/:id/rows?page=&page_size=&sort_column=&sort_order=&filters=
  rows: (id, pageState) => httpClient.get(`/datasets/${id}/rows`, { params: toPageParams(pageState) }),

  // GET /api/datasets/:id/rows/distinct?column=
  rowsDistinct: (id, column) =>
    httpClient.get(`/datasets/${id}/rows/distinct`, { params: { column } })
}

export default datasetsAPI
