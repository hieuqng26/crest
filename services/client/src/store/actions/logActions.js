import { logAPI } from '@/api'

export const logActions = {
  getAllLogs(context, payload) {
    return logAPI.getAllLogs(payload, context.state.jwt.accessToken)
  },
  getLogsbyUser(context, userEmail) {
    return logAPI.getLogsbyUser(userEmail, context.state.jwt.accessToken)
  },
  log(context, logData) {
    return logAPI.log(logData, context.state.jwt.accessToken)
  }
}
