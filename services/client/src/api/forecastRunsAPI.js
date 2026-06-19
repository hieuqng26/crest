import { httpClient } from './httpClient'

const forecastRunsAPI = {
  list:    (params)  => httpClient.get('/forecast-runs', { params }),
  create:  (payload) => httpClient.post('/forecast-runs', payload),
  get:     (runId)   => httpClient.get(`/forecast-runs/${runId}`),
  refs:       (runId)   => httpClient.get(`/forecast-runs/${runId}/refs`),
  delete:     (runId)   => httpClient.delete(`/forecast-runs/${runId}`, { validateStatus: (s) => s < 500 }),
  bulkDelete: (runIds)  => httpClient.post('/forecast-runs/bulk-delete', { run_ids: runIds }),
  cancel:  (runId)   => httpClient.post(`/forecast-runs/${runId}/cancel`),
  rerun:   (runId)   => httpClient.post(`/forecast-runs/${runId}/rerun`),
  logs:    (runId)   => httpClient.get(`/forecast-runs/${runId}/logs`),
  results: (runId) => httpClient.get(`/forecast-runs/${runId}/results`),
}

export default forecastRunsAPI
