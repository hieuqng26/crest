import { logAPI } from '@/api'

export const logActions = {
  getAllLogs(context, payload) {
    return logAPI.getAllLogs(payload)
  },
  getLogsbyUser(context, userEmail) {
    return logAPI.getLogsbyUser(userEmail)
  },
  log(context, logData) {
    return logAPI.log(logData)
  }
}
