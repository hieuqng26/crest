import calibrationsAPI from '@/api/calibrationsAPI'

export const STATUS_META = {
  success: { severity: 'success', icon: 'pi pi-check-circle',  color: 'text-green-500'  },
  running: { severity: 'warning', icon: 'pi pi-spin pi-spinner', color: 'text-yellow-600' },
  queued:  { severity: 'info',    icon: 'pi pi-clock',         color: 'text-blue-500'   },
  failed:  { severity: 'danger',  icon: 'pi pi-times-circle',  color: 'text-red-500'    }
}

export const statusSeverity = (s) => STATUS_META[s]?.severity ?? 'secondary'
export const statusIcon     = (s) => STATUS_META[s]?.icon ?? 'pi pi-circle'
export const statusColor    = (s) => STATUS_META[s]?.color ?? 'text-color-secondary'

const parseDate = (s) => {
  if (!s) return null
  const norm = s.includes('T') ? s : s.replace(' ', 'T') + ':00Z'
  const d = new Date(norm)
  return isNaN(d.valueOf()) ? null : d
}

export const duration = (startedIso, finishedIso, status) => {
  const start = parseDate(startedIso)
  if (!start) return '—'
  const end = parseDate(finishedIso) || (status === 'running' ? new Date() : null)
  if (!end) return status === 'running' ? 'live' : '—'
  const totalSec = Math.max(0, Math.round((end - start) / 1000))
  if (totalSec < 60) return `${totalSec}s`
  const m = Math.floor(totalSec / 60), s = totalSec % 60
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`
  const h = Math.floor(m / 60), mm = m % 60
  return `${h}h ${mm}m`
}

export const isTimeSeries = (algorithm) =>
  ['ARIMA', 'OLS', 'Ridge'].includes(algorithm)

export const getRun = async (runId) => {
  try {
    const { data } = await calibrationsAPI.get(runId)
    return data
  } catch {
    // Return a skeleton for brand-new runs not yet in DB (queued but Celery hasn't started yet)
    return {
      run_id: runId,
      config_name: '—',
      algorithm: '—',
      dataset_name: '—',
      status: 'queued',
      progress: 0,
      triggered_by: '—',
      started_at: new Date().toISOString().slice(0, 16).replace('T', ' '),
      finished_at: null
    }
  }
}
