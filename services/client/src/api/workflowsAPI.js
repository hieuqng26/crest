import { httpClient } from './httpClient'

const workflowsAPI = {
  resolveDatasets: () => httpClient.get('/workflows/resolve-datasets'),
  create:          (body)   => httpClient.post('/workflows/', body),
  list:            (params = {}) => httpClient.get('/workflows/', { params }),
  get:             (runId)  => httpClient.get(`/workflows/${runId}`),
  cancel:          (runId)  => httpClient.post(`/workflows/${runId}/cancel`),
  rerun:           (runId)  => httpClient.post(`/workflows/${runId}/rerun`),
  activate:        (runId)  => httpClient.put(`/workflows/${runId}/activate`),
  delete:          (runId)  => httpClient.delete(`/workflows/${runId}`, { validateStatus: (s) => s < 500 }),
}

export default workflowsAPI
