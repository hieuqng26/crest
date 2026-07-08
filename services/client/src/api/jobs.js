// Unifies calibration (training) / forecast / credit-risk (analysis) runs into
// one shape for the v2 Job History + Job Detail screens. Each underlying API
// keeps its own shape — this module only normalizes for the shared UI and
// dispatches actions to whichever API a given `kind` maps to.
import calibrationsAPI from './calibrationsAPI'
import forecastRunsAPI from './forecastRunsAPI'
import creditRiskAPI from './creditRiskAPI'

export const KIND = { TRAINING: 'training', FORECAST: 'forecast', ANALYSIS: 'analysis' }

const normalizeCalibration = (r) => ({
  run_id: r.run_id,
  kind: KIND.TRAINING,
  name: r.run_name || r.config_name || r.run_id.slice(0, 8),
  ref: r.dataset_name || '—',
  status: r.status,
  progress: r.progress ?? (r.status === 'success' ? 100 : 0),
  started_at: r.started_at,
  finished_at: r.finished_at,
  triggered_by: r.triggered_by,
  raw: r
})

const normalizeForecast = (r) => ({
  run_id: r.run_id,
  kind: KIND.FORECAST,
  name: r.name || r.target_col || r.run_id.slice(0, 8),
  ref: [r.target_col, r.config_name].filter(Boolean).join(' · ') || r.dataset_name || '—',
  status: r.status,
  progress: r.progress ?? (r.status === 'success' ? 100 : 0),
  started_at: r.started_at ?? r.created_at,
  finished_at: r.finished_at,
  triggered_by: r.triggered_by,
  raw: r
})

const normalizeCreditRisk = (r) => ({
  run_id: r.run_id,
  kind: KIND.ANALYSIS,
  name: r.dataset_name || r.run_id.slice(0, 8),
  ref: r.dataset_name || '—',
  status: r.status,
  progress: r.progress ?? (r.status === 'success' ? 100 : 0),
  started_at: r.started_at ?? r.created_at,
  finished_at: r.finished_at,
  triggered_by: r.triggered_by,
  raw: r
})

async function listJobs() {
  const [cRes, fRes, xRes] = await Promise.allSettled([
    calibrationsAPI.list({ per_page: 200 }),
    forecastRunsAPI.list({ per_page: 200 }),
    creditRiskAPI.listRuns({ per_page: 200 })
  ])
  const training =
    cRes.status === 'fulfilled' ? (cRes.value.data.items ?? cRes.value.data ?? []).map(normalizeCalibration) : []
  const forecast =
    fRes.status === 'fulfilled' ? (fRes.value.data.items ?? fRes.value.data ?? []).map(normalizeForecast) : []
  const analysis =
    xRes.status === 'fulfilled' ? (xRes.value.data.items ?? xRes.value.data ?? []).map(normalizeCreditRisk) : []
  return [...training, ...forecast, ...analysis]
}

async function getJob(kind, runId) {
  if (kind === KIND.TRAINING) {
    const { data } = await calibrationsAPI.get(runId)
    return normalizeCalibration(data)
  }
  if (kind === KIND.FORECAST) {
    const { data } = await forecastRunsAPI.get(runId)
    return normalizeForecast(data)
  }
  const { data } = await creditRiskAPI.getRun(runId)
  return normalizeCreditRisk(data)
}

const getJobLogs = (kind, runId) => {
  if (kind === KIND.TRAINING) return calibrationsAPI.logs(runId)
  if (kind === KIND.FORECAST) return forecastRunsAPI.logs(runId)
  return creditRiskAPI.getRunLogs(runId)
}

const cancelJob = (kind, runId) => {
  if (kind === KIND.TRAINING) return calibrationsAPI.cancel(runId)
  if (kind === KIND.FORECAST) return forecastRunsAPI.cancel(runId)
  return creditRiskAPI.cancelRun(runId)
}

const deleteJob = (kind, runId) => {
  if (kind === KIND.TRAINING) return calibrationsAPI.delete(runId)
  if (kind === KIND.FORECAST) return forecastRunsAPI.delete(runId)
  return creditRiskAPI.deleteRun(runId)
}

const rerunJob = (kind, runId) => {
  if (kind === KIND.TRAINING) return calibrationsAPI.recalibrate(runId, {})
  if (kind === KIND.FORECAST) return forecastRunsAPI.rerun(runId)
  return creditRiskAPI.rerunRun(runId)
}

// Results tables only apply to forecast / analysis kinds (training uses the
// Segment models table instead — see calibrationsAPI.segments).
const resultsFetchPage = (kind, runId, pageState) =>
  kind === KIND.FORECAST
    ? forecastRunsAPI.results(runId, pageState)
    : creditRiskAPI.getRunResults(runId, pageState)

const resultsFetchDistinct = (kind, runId, column) =>
  kind === KIND.FORECAST
    ? forecastRunsAPI.resultsDistinct(runId, column)
    : creditRiskAPI.getRunResultsDistinct(runId, column)

export default {
  KIND,
  listJobs,
  getJob,
  getJobLogs,
  cancelJob,
  deleteJob,
  rerunJob,
  resultsFetchPage,
  resultsFetchDistinct
}
