import { httpClient } from './httpClient'

const modelConfigsAPI = {
  registry:   ()       => httpClient.get('/model-configs/registry'),
  list:       ()       => httpClient.get('/model-configs/'),
  get:        (id)     => httpClient.get(`/model-configs/${id}`),
  create:     (body)   => httpClient.post('/model-configs/', body),
  update:     (id, body) => httpClient.patch(`/model-configs/${id}`, body),
  delete:     (id)     => httpClient.delete(`/model-configs/${id}`),
  bulkDelete: (ids)    => httpClient.post('/model-configs/bulk-delete', { ids }),
}

export default modelConfigsAPI
