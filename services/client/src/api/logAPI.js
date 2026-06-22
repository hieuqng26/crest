import httpClient from '@/api/httpClient'

const logAPI = {
  getAllLogs: (logData) =>
    httpClient.post(`/log/all`, logData, {
      headers: {
        'Content-Type': 'application/json'
      }
    }),
  getLogsbyUser: (userEmail) =>
    httpClient.get(`/log/email/${userEmail}`),
  log: (logData) =>
    httpClient.post(`/log/add`, logData, {
      headers: {
        'Content-Type': 'application/json'
      }
    })
}

export default logAPI
