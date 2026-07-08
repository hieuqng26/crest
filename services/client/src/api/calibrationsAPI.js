import { httpClient } from './httpClient'
import { toPageParams } from '@/utils/tablePaging'

const calibrationsAPI = {
  list:        (params = {})  => httpClient.get('/calibrations/', { params }),
  get:         (runId)        => httpClient.get(`/calibrations/${runId}`),
  create:      (body)         => httpClient.post('/calibrations/', body),
  diagnostics:    (runId)            => httpClient.get(`/calibrations/${runId}/diagnostics`),
  getDiagnostics: (runId, segKey)    => httpClient.get(`/calibrations/${runId}/diagnostics`, { params: segKey ? { segment_key: segKey } : {} }),
  segments:       (runId, params = {}) => httpClient.get(`/calibrations/${runId}/segments`, { params }),
  segmentSectors: (runId)            => httpClient.get(`/calibrations/${runId}/segments/sectors`),
  forecast:    (runId)        => httpClient.get(`/calibrations/${runId}/forecast`),

  // Paginated backtest predictions (non-segmented run) — backs ForecastTab.vue
  backtestPredictions: (runId, pageState) =>
    httpClient.get(`/calibrations/${runId}/backtest/predictions`, { params: toPageParams(pageState) }),
  backtestPredictionsDistinct: (runId, column) =>
    httpClient.get(`/calibrations/${runId}/backtest/predictions/distinct`, { params: { column } }),

  // Paginated backtest predictions (per segment) — backs SegmentBacktestTab.vue
  segmentBacktestPredictions: (runId, segKey, pageState) =>
    httpClient.get(`/calibrations/${runId}/segments/${segKey}/backtest/predictions`, { params: toPageParams(pageState) }),
  segmentBacktestPredictionsDistinct: (runId, segKey, column) =>
    httpClient.get(`/calibrations/${runId}/segments/${segKey}/backtest/predictions/distinct`, { params: { column } }),
  recalibrate: (runId, body)  => httpClient.post(`/calibrations/${runId}/recalibrate`, body),
  rerunSegment: (runId, segmentKey, body) =>
    httpClient.post(`/calibrations/${runId}/segments/${segmentKey}/recalibrate`, body),
  logs:        (runId, params = {}) => httpClient.get(`/calibrations/${runId}/logs`, { params }),
  cancel:      (runId)        => httpClient.post(`/calibrations/${runId}/cancel`),
  refs:        (runId)        => httpClient.get(`/calibrations/${runId}/refs`),
  delete:      (runId)        => httpClient.delete(`/calibrations/${runId}`, { validateStatus: (s) => s < 500 }),
  bulkDelete:  (runIds)       => httpClient.post('/calibrations/bulk-delete', { run_ids: runIds }),
}

export default calibrationsAPI
