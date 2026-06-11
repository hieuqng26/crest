import { fileAPI } from '@/api'

export const fileActions = {
  uploadInputData(context, payload) {
    const { formData, module, submodule } = payload
    return fileAPI.uploadInputData(
      formData,
      module,
      submodule,
      context.state.jwt.accessToken
    )
  },
  uploadPortfolioData(context, payload) {
    const { formData, module, submodule } = payload
    return fileAPI.uploadPortfolioData(
      formData,
      module,
      submodule,
      context.state.jwt.accessToken
    )
  },
  uploadScenarioConfig(context, payload) {
    return fileAPI.uploadScenarioConfig(
      payload.formData,
      context.state.jwt.accessToken
    )
  },
  downloadFile(context, payload) {
    const {
      jobId,
      module,
      submodule,
      type,
      dbName,
      fileType,
      downloadFileName,
      isStaging
    } = payload
    return fileAPI.downloadFile(
      jobId,
      module,
      submodule,
      type,
      dbName,
      fileType,
      downloadFileName,
      isStaging,
      context.state.jwt.accessToken
    )
  }
}
