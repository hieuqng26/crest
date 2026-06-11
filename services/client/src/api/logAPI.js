import { httpClient, setAuthHeader } from '@/api/httpClient'

const logAPI = {
  getAllLogs: (logData, jwt) =>
    httpClient.post(`/log/all`, logData, {
      headers: {
        ...setAuthHeader(jwt),
        'Content-Type': 'application/json'
      }
    }),
  getLogsbyUser: (userEmail, jwt) =>
    httpClient.get(`/log/email/${userEmail}`, { headers: setAuthHeader(jwt) }),
  log: (logData, jwt) =>
    httpClient.post(`/log/add`, logData, {
      headers: {
        ...setAuthHeader(jwt),
        'Content-Type': 'application/json'
      }
    })
}

export default logAPI
