import { httpClient, setAuthHeader } from '@/api/httpClient'

const dataAPI = {
  getStagingInput: (
    module,
    submodule,
    dbName,
    columns,
    filter_columns,
    filter_values,
    sort_column,
    sort_order,
    page,
    page_size,
    jobId,
    get_size,
    jwt
  ) =>
    httpClient.post(
      `/data/staging/${module}/${submodule}`,
      {
        dbName: dbName,
        columns: columns,
        filter_columns: filter_columns,
        filter_values: JSON.stringify(filter_values),
        sort_column: sort_column,
        sort_order: sort_order,
        page: page,
        page_size: page_size,
        jobId: jobId,
        get_size: get_size
      },
      {
        headers: {
          ...setAuthHeader(jwt),
          'Content-Type': 'application/json'
        }
      }
    ),
  getMarketData: (category, filter_columns, filter_values, jwt) =>
    httpClient.post(
      `/data/market-data/${category}`,
      {
        filter_columns: filter_columns,
        filter_values: JSON.stringify(filter_values)
      },
      {
        headers: {
          ...setAuthHeader(jwt),
          'Content-Type': 'application/json'
        }
      }
    )
}

export default dataAPI
