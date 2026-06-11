import { httpClient, setAuthHeader } from '@/api/httpClient'

const authAPI = {
  login: (userData) => httpClient.post(`/auth/login`, userData),
  refreshToken: (jwt) => httpClient.post(`/auth/refresh`, null, { headers: setAuthHeader(jwt) }),
  logout: (jwt) => httpClient.post(`/auth/logout`, null, { headers: setAuthHeader(jwt) })
}

export default authAPI
