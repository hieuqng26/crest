import { httpClient } from './httpClient'

const creditRiskAPI = {
  pdRatings: (curve = 'moodys') =>
    httpClient.get('/credit-risk/pd-ratings', { params: { curve } }),

  clients: (datasetId = null, mock = false) => {
    const params = mock ? { mock: 'true' } : { dataset_id: datasetId }
    return httpClient.get('/credit-risk/clients', { params })
  },

  kmv: (payload) =>
    httpClient.post('/credit-risk/kmv', payload),

  ecl: (payload) =>
    httpClient.post('/credit-risk/ecl', payload),

  listRuns:        ()              => httpClient.get('/credit-risk/runs'),
  createRun:       (payload)       => httpClient.post('/credit-risk/runs', payload),
  getActiveRun:    ()              => httpClient.get('/credit-risk/runs/active'),
  getRun:          (runId)         => httpClient.get(`/credit-risk/runs/${runId}`),
  getClientResult: (runId, cId)    => httpClient.get(`/credit-risk/runs/${runId}/client/${cId}`),
  getRunLogs:      (runId)         => httpClient.get(`/credit-risk/runs/${runId}/logs`),
  setActiveRun:    (runId)         => httpClient.put(`/credit-risk/runs/${runId}/active`),
  rerunRun:        (runId)         => httpClient.post(`/credit-risk/runs/${runId}/rerun`),
  deleteRun:       (runId)         => httpClient.delete(`/credit-risk/runs/${runId}`),
}

export default creditRiskAPI
