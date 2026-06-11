import { httpClient, setAuthHeader } from '@/api/httpClient'

const jobAPI = {
  getAllJobs: (jwt) => httpClient.get(`/job/all`, { headers: setAuthHeader(jwt) }),
  getJob: (jobId, jwt) => httpClient.get(`/job/id/${jobId}`, { headers: setAuthHeader(jwt) }),
  getCurrentJobs: (jwt) => httpClient.get(`/job/current`, { headers: setAuthHeader(jwt) }),
  getJobHistory: (jobId, jwt) =>
    httpClient.get(`/job/history/${jobId}`, { headers: setAuthHeader(jwt) }),
  getJobsByModule: (
    modules,
    filter_columns,
    filter_values,
    date_from,
    date_to,
    sort_column,
    sort_order,
    page,
    page_size,
    get_size,
    jwt
  ) =>
    httpClient.post(
      `/job/module`,
      {
        modules: modules,
        filter_columns: filter_columns,
        filter_values: JSON.stringify(filter_values),
        date_from: date_from,
        date_to: date_to,
        sort_column: sort_column,
        sort_order: sort_order,
        page: page,
        page_size: page_size,
        get_size: get_size
      },
      {
        headers: {
          ...setAuthHeader(jwt),
          'Content-Type': 'application/json'
        }
      }
    ),
  getLatestJob: (email, module, submodule, jwt) =>
    httpClient.post(
      `/job/latest`,
      { email: email, module: module, submodule: submodule },
      {
        headers: {
          ...setAuthHeader(jwt),
          'Content-Type': 'application/json'
        }
      }
    ),
  getJobByEmail: (email, jwt) =>
    httpClient.get(`/job/email/${email}`, { headers: setAuthHeader(jwt) }),
  addJob: (inputData, jwt) =>
    httpClient.post(`/job/add`, inputData, {
      headers: {
        ...setAuthHeader(jwt),
        'Content-Type': 'application/json'
      }
    }),
  runJob: (jobId, jwt) =>
    httpClient.post(`/job/run/${jobId}`, null, { headers: setAuthHeader(jwt) }),
  cancelJob: (jobId, jwt) =>
    httpClient.post(`/job/cancel/${jobId}`, null, { headers: setAuthHeader(jwt) }),
  deleteJob: (jobId, jwt) =>
    httpClient.delete(`/job/delete/${jobId}`, { headers: setAuthHeader(jwt) }),
  updateJob: (jobId, jobData, jwt) =>
    httpClient.put(`/job/update/${jobId}`, jobData, { headers: setAuthHeader(jwt) }),
  getJobStatus: (jobId, jwt) =>
    httpClient.put(`/job/get_status/${jobId}`, null, { headers: setAuthHeader(jwt) }),
  getJobData: (
    jobId,
    type,
    dbName,
    columns,
    filter_columns,
    filter_values,
    sort_column,
    sort_order,
    page,
    page_size,
    get_names,
    get_size,
    jwt
  ) =>
    httpClient.post(
      `/job/data/${jobId}/${type}/${dbName}`,
      {
        columns: columns,
        filter_columns: filter_columns,
        filter_values: JSON.stringify(filter_values),
        sort_column: sort_column,
        sort_order: sort_order,
        page: page,
        page_size: page_size,
        get_names: get_names,
        get_size: get_size
      },
      {
        headers: {
          ...setAuthHeader(jwt),
          'Content-Type': 'application/json'
        }
      }
    ),
  getStagingJobs: (jwt) => httpClient.get(`/job/staging_jobs`, { headers: setAuthHeader(jwt) }),
  getStagingJobDetail: (jobId, jwt) =>
    httpClient.get(`/job/staging_job_detail/${jobId}`, { headers: setAuthHeader(jwt) }),
  cancelStagingJob: (jobId, jwt) =>
    httpClient.post(`/job/cancel_staging/${jobId}`, null, { headers: setAuthHeader(jwt) }),
  deleteStagingJob: (jobId, jwt) =>
    httpClient.delete(`/job/delete_staging/${jobId}`, { headers: setAuthHeader(jwt) }),
  rerunStaging: (jwt) =>
    httpClient.post(`/job/rerun_staging`, null, { headers: setAuthHeader(jwt) }),
  updateStagingProgress: (jobId, jwt) =>
    httpClient.put(`/job/update_staging_progress`, { jobId }, { headers: setAuthHeader(jwt) })
}

export default jobAPI
