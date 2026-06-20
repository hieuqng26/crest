// System-wide datetime configuration.
// Change TIMEZONE to match the deployment region:
//   'Asia/Singapore'     (SG, UTC+8)
//   'Asia/Ho_Chi_Minh'  (VN, UTC+7)
//   'Asia/Jakarta'       (ID, UTC+7)
//   'Asia/Kuala_Lumpur'  (MY, UTC+8)
export const DATETIME_CONFIG = {
  timezone: 'Asia/Singapore',
  locale: 'en-GB',
}

/**
 * Format an ISO date string as DD/MM/YYYY HH:MM:SS in the configured timezone.
 * Returns '—' for null/undefined/invalid input.
 */
export function fmtDate(iso) {
  if (!iso) return '—'
  // Normalise Python isoformat(): replace space separator, then force 'Z' if no tz offset
  // present — MSSQL DateTime columns strip tzinfo on read, so naive strings must be treated as UTC.
  let s = iso.includes('T') ? iso : iso.replace(' ', 'T')
  if (!s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return iso

  const { timezone, locale } = DATETIME_CONFIG
  const date = d.toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: timezone })
  const time = d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: timezone })
  return `${date} ${time}`
}

/**
 * Short date-only format: DD/MM/YYYY
 */
export function fmtDateShort(iso) {
  if (!iso) return '—'
  let s = iso.includes('T') ? iso : iso.replace(' ', 'T')
  if (!s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(DATETIME_CONFIG.locale, {
    day: '2-digit', month: '2-digit', year: 'numeric',
    timeZone: DATETIME_CONFIG.timezone,
  })
}

function _toDate(iso) {
  if (!iso) return null
  let s = iso.includes('T') ? iso : iso.replace(' ', 'T')
  if (!s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) s += 'Z'
  const d = new Date(s)
  return isNaN(d.getTime()) ? null : d
}

/**
 * Human-readable elapsed time between two ISO timestamps.
 * Returns 'live' for a running job with no finish time, '—' when unknown.
 */
export function duration(startedIso, finishedIso, status) {
  const start = _toDate(startedIso)
  if (!start) return '—'
  const end = _toDate(finishedIso) || (status === 'running' ? new Date() : null)
  if (!end) return status === 'running' ? 'live' : '—'
  const totalSec = Math.max(0, Math.round((end - start) / 1000))
  if (totalSec < 60) return `${totalSec}s`
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return `${h}h ${mm}m`
}
