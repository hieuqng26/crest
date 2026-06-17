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
