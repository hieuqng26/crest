// Shared query-param shape for CommonDataTable's fetchPage → backend contract:
// GET .../<resource>?page=&page_size=&sort_column=&sort_order=&filters=
export function toPageParams({ page = 0, pageSize = 50, sortColumn = null, sortOrder = null, filters = null } = {}) {
  const params = { page, page_size: pageSize }
  if (sortColumn) params.sort_column = sortColumn
  if (sortOrder)  params.sort_order  = sortOrder
  if (filters && Object.keys(filters).length) params.filters = JSON.stringify(filters)
  return params
}
