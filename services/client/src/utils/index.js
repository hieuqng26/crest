export function isValidJwt(jwt) {
  if (!jwt || jwt.split('.').length < 3) {
    return false
  }
  const data = JSON.parse(atob(jwt.split('.')[1]))
  const exp = new Date(data.exp * 1000)
  const now = new Date()
  return now < exp
}

export { fmtDate, fmtDateShort, DATETIME_CONFIG } from './datetime'
import { fmtDate, fmtDateShort } from './datetime'

// Accepts both ISO strings and Date objects (some views pre-convert to Date for
// client-side sorting) — normalise to ISO before the canonical formatters.
export function formatDate(date, showTime = false) {
  if (!date) return '—'
  const iso = date instanceof Date ? date.toISOString() : date
  return showTime ? fmtDate(iso) : fmtDateShort(iso)
}
