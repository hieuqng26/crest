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
  // Python isoformat() may omit 'T' or timezone suffix
  const s = iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z'
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
  const s = iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(DATETIME_CONFIG.locale, {
    day: '2-digit', month: '2-digit', year: 'numeric',
    timeZone: DATETIME_CONFIG.timezone,
  })
}
