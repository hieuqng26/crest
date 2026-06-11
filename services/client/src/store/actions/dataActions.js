import { dataAPI } from '@/api'

export const dataActions = {
  getStagingInput(context, payload) {
    const {
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
      get_size
    } = payload
    return dataAPI.getStagingInput(
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
      context.state.jwt.accessToken
    )
  },
  getMarketData(context, payload) {
    const { category, filter_columns, filter_values } = payload
    return dataAPI.getMarketData(
      category,
      filter_columns,
      filter_values,
      context.state.jwt.accessToken
    )
  }
}
