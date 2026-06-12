import { httpClient } from './httpClient'

const calibrationsAPI = {
  list:        (params = {})  => httpClient.get('/calibrations/', { params }),
  get:         (runId)        => httpClient.get(`/calibrations/${runId}`),
  create:      (body)         => httpClient.post('/calibrations/', body),
  diagnostics: (runId)        => httpClient.get(`/calibrations/${runId}/diagnostics`),
  forecast:    (runId)        => httpClient.get(`/calibrations/${runId}/forecast`),
  recalibrate: (runId, body)  => httpClient.post(`/calibrations/${runId}/recalibrate`, body),
}

export default calibrationsAPI
