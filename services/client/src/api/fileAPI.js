import { httpClient, setAuthHeader } from '@/api/httpClient'

const fileAPI = {
  uploadInputData: (formData, module, submodule, jwt) =>
    httpClient.post(
      `/files/upload_input_data/${module}/${submodule}`,
      formData,
      {
        headers: {
          ...setAuthHeader(jwt),
          'Content-Type': 'multipart/form-data'
        }
      }
    ),
  uploadPortfolioData: (formData, module, submodule, jwt) =>
    httpClient.post(
      `/files/upload_portfolio_data/${module}/${submodule}`,
      formData,
      {
        headers: {
          ...setAuthHeader(jwt),
          'Content-Type': 'multipart/form-data'
        }
      }
    ),
  uploadScenarioConfig: (formData, jwt) =>
    httpClient.post(`/files/ore/upload_scenario_config`, formData, {
      headers: {
        ...setAuthHeader(jwt),
        'Content-Type': 'multipart/form-data'
      }
    }),
  downloadFile: (
    jwt,
    jobId,
    module,
    submodule,
    type,
    dbName,
    fileType,
    downloadFileName,
    isStaging
  ) =>
    httpClient.post(
      `/files/download`,
      {
        jobId: jobId,
        module: module,
        submodule: submodule,
        type: type,
        dbName: dbName,
        fileType: fileType,
        downloadFileName: downloadFileName,
        isStaging: isStaging
      },
      {
        headers: setAuthHeader(jwt),
        responseType: 'json'
      }
    )
}

export default fileAPI
