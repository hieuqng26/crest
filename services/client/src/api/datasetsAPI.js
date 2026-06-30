import { httpClient } from './httpClient'

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

  // Rows endpoint — used by DatasetView lazy paginator
  // GET /api/datasets/:id/rows?offset=&limit=&sort=&order=&filter=
  rows: (id, { offset = 0, limit = 50, sort = null, order = null, filter = '' } = {}) => {
    const params = { offset, limit }
    if (sort)   params.sort  = sort
    if (order)  params.order = order
    if (filter) params.filter = filter
    return httpClient.get(`/datasets/${id}/rows`, { params })
  }
}

export default datasetsAPI
