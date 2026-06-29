import { httpClient } from './httpClient'

const calibrationsAPI = {
  list:        (params = {})  => httpClient.get('/calibrations/', { params }),
  get:         (runId)        => httpClient.get(`/calibrations/${runId}`),
  create:      (body)         => httpClient.post('/calibrations/', body),
  diagnostics:    (runId)            => httpClient.get(`/calibrations/${runId}/diagnostics`),
  getDiagnostics: (runId, segKey)    => httpClient.get(`/calibrations/${runId}/diagnostics`, { params: segKey ? { segment_key: segKey } : {} }),
  segments:       (runId)            => httpClient.get(`/calibrations/${runId}/segments`),
  forecast:    (runId)        => httpClient.get(`/calibrations/${runId}/forecast`),
  recalibrate: (runId, body)  => httpClient.post(`/calibrations/${runId}/recalibrate`, body),
  logs:        (runId)        => httpClient.get(`/calibrations/${runId}/logs`),
  cancel:      (runId)        => httpClient.post(`/calibrations/${runId}/cancel`),
  refs:        (runId)        => httpClient.get(`/calibrations/${runId}/refs`),
  delete:      (runId)        => httpClient.delete(`/calibrations/${runId}`, { validateStatus: (s) => s < 500 }),
  bulkDelete:  (runIds)       => httpClient.post('/calibrations/bulk-delete', { run_ids: runIds }),
}

export default calibrationsAPI
