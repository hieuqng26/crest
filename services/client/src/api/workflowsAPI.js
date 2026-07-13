import { httpClient } from './httpClient'
import { toPageParams } from '@/utils/tablePaging'

const workflowsAPI = {
  resolveDatasets: () => httpClient.get('/workflows/resolve-datasets'),
  create:          (body)   => httpClient.post('/workflows/', body),
  list:            (params = {}) => httpClient.get('/workflows/', { params }),
  get:             (runId, params = {}) => httpClient.get(`/workflows/${runId}`, { params }),
  cancel:          (runId)  => httpClient.post(`/workflows/${runId}/cancel`),
  rerun:           (runId)  => httpClient.post(`/workflows/${runId}/rerun`),
  activate:        (runId)  => httpClient.put(`/workflows/${runId}/activate`),
  delete:          (runId)  => httpClient.delete(`/workflows/${runId}`, { validateStatus: (s) => s < 500 }),

  // Combined forecast results across all the workflow's targets (backs the Forecast tab).
  forecastResults:         (runId, pageState) => httpClient.get(`/workflows/${runId}/forecast-results`, { params: toPageParams(pageState) }),
  forecastResultsDistinct: (runId, column)    => httpClient.get(`/workflows/${runId}/forecast-results/distinct`, { params: { column } }),

  // Unified training + forecast + credit logs (backs the Overview log panel).
  logs:         (runId, pageState) => httpClient.get(`/workflows/${runId}/logs`, { params: toPageParams(pageState) }),
  logsDistinct: (runId, column)    => httpClient.get(`/workflows/${runId}/logs/distinct`, { params: { column } }),

  // Downloadable exports (backs the Download tab): list outputs, request an async
  // build (csv/xlsx), poll jobs, and download the finished file as a blob.
  exportOutputs:  (runId)                 => httpClient.get(`/workflows/${runId}/exports/outputs`),
  listExports:    (runId)                 => httpClient.get(`/workflows/${runId}/exports`),
  createExport:   (runId, output, format) => httpClient.post(`/workflows/${runId}/exports`, { output, format }),
  getExport:      (runId, jobId)          => httpClient.get(`/workflows/${runId}/exports/${jobId}`),
  downloadExport: (runId, jobId)          => httpClient.get(`/workflows/${runId}/exports/${jobId}/download`, { responseType: 'blob' }),
}

export default workflowsAPI
