import httpClient from '@/api/httpClient'

const authAPI = {
  login: (credentials) => httpClient.post('/auth/login', credentials),
  refresh: () => httpClient.post('/auth/refresh'),
  logout: () => httpClient.post('/auth/logout'),
  me: () => httpClient.get('/auth/me'),
  changePassword: (payload) => httpClient.post('/auth/change-password', payload)
}
export default authAPI
