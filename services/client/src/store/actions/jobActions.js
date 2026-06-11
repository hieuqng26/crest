import { jobAPI } from '@/api'

export const jobActions = {
  addJob(context, payload) {
    return jobAPI.addJob(payload, context.state.jwt.accessToken)
  },
  runJob(context, jobId) {
    return jobAPI.runJob(jobId, context.state.jwt.accessToken)
  },
  cancelJob(context, jobId) {
    return jobAPI.cancelJob(jobId, context.state.jwt.accessToken)
  },
  deleteJob(context, jobId) {
    return jobAPI.deleteJob(jobId, context.state.jwt.accessToken)
  },
  updateJob(context, payload) {
    const { jobId, jobData } = payload
    return jobAPI.updateJob(jobId, jobData, context.state.jwt.accessToken)
  },
  getJobStatus(context, jobId) {
    return jobAPI.getJobStatus(jobId, context.state.jwt.accessToken)
  },
  storeResult(context, payload) {
    const { model, data } = payload
    return fileAPI.storeResult(context.state.jwt.accessToken, model, data)
  },
  getAllJobs(context) {
    return jobAPI.getAllJobs(context.state.jwt.accessToken)
  },
  getCurrentJobs(context) {
    return jobAPI.getCurrentJobs(context.state.jwt.accessToken)
  },
  getJobsByModule(context, payload) {
    const {
      modules,
      filter_columns,
      filter_values,
      date_from,
      date_to,
      sort_column,
      sort_order,
      page,
      page_size,
      get_size
    } = payload
    return jobAPI.getJobsByModule(
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
      context.state.jwt.accessToken
    )
  },
  getLatestJob(context, payload) {
    const { email, module, submodule } = payload
    return jobAPI.getLatestJob(email, module, submodule, context.state.jwt.accessToken)
  },
  getJob(context, jobId) {
    return jobAPI.getJob(jobId, context.state.jwt.accessToken)
  },
  getJobHistory(context, jobId) {
    return jobAPI.getJobHistory(jobId, context.state.jwt.accessToken)
  },
  getJobData(context, payload) {
    const {
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
      get_size
    } = payload
    return jobAPI.getJobData(
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
      context.state.jwt.accessToken
    )
  },
  getStagingJobs(context) {
    return jobAPI.getStagingJobs(context.state.jwt.accessToken)
  },
  getStagingJobDetail(context, jobId) {
    return jobAPI.getStagingJobDetail(jobId, context.state.jwt.accessToken)
  },
  rerunStaging(context) {
    return jobAPI.rerunStaging(context.state.jwt.accessToken)
  },
  cancelStagingJob(context, jobId) {
    return jobAPI.cancelStagingJob(jobId, context.state.jwt.accessToken)
  },
  deleteStagingJob(context, jobId) {
    return jobAPI.deleteStagingJob(jobId, context.state.jwt.accessToken)
  },
  updateStagingProgress(context, jobId) {
    return jobAPI.updateStagingProgress(jobId, context.state.jwt.accessToken)
  }
}
