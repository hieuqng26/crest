// Client-side counterpart to the backend's table_query.py — used to wrap an
// already-loaded, small in-memory array (e.g. one client's ECL/PD-LGD rows,
// or a run's segment list) as a CommonDataTable `fetchPage` source, so its
// per-column filter/sort/pagination behave the same as the server-driven
// tables without needing a backend round trip for genuinely small data.
export function queryLocalRows(allRows, { page = 0, pageSize = 50, sortColumn = null, sortOrder = null, filters = {} } = {}) {
  let rows = allRows

  for (const [field, spec] of Object.entries(filters || {})) {
    const { mode, value } = spec || {}
    if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) continue
    if (mode === 'in') {
      const allowed = new Set((Array.isArray(value) ? value : [value]).map(String))
      rows = rows.filter((r) => allowed.has(String(r[field])))
    } else {
      const needle = String(value).toLowerCase()
      rows = rows.filter((r) => String(r[field] ?? '').toLowerCase().includes(needle))
    }
  }

  const total = rows.length

  if (sortColumn) {
    const dir = sortOrder === 'desc' ? -1 : 1
    rows = [...rows].sort((a, b) => {
      const av = a[sortColumn]
      const bv = b[sortColumn]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (av < bv) return -dir
      if (av > bv) return dir
      return 0
    })
  }

  const offset = page * pageSize
  return { rows: rows.slice(offset, offset + pageSize), total }
}

// Adapts queryLocalRows to CommonDataTable's fetchPage contract, which
// expects an axios-response-shaped `{ data }` promise.
export function localFetchPage(getRows) {
  return async (params) => ({ data: queryLocalRows(getRows(), params) })
}
